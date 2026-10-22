"""记忆库（memory/）的回归测试。

覆盖：frontmatter 解析、语料结构/生命周期、检索（含 id/scope）、三套评测、写入路径（spool→drain）、
去重与信任边界。全部用标准库，不联网、不写仓库里的记忆（写入测试在临时副本上做）。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_ROOT = ROOT / "memory"
TOOL = MEMORY_ROOT / "tools" / "memory.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("sysml_memory_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    # dataclass 需要模块先注册进 sys.modules（否则 cls.__module__ 查不到）
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TOOL_MODULE = _load_tool()


def _fts5_available() -> bool:
    try:
        sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False


HAS_FTS5 = _fts5_available()


def _run(args, memory_root=None, cwd=ROOT):
    command = [sys.executable, str(TOOL), "--root", str(ROOT)]
    if memory_root is not None:
        command += ["--memory-root", str(memory_root)]
    command += list(args)
    return subprocess.run(command, capture_output=True, text=True, cwd=str(cwd), timeout=120)


def _candidate(record_id="mem-20260101-9001", created="2026-01-01T10:00:00+08:00", title=None):
    title = title or "测试用候选记忆：记忆库写入路径的样例"
    slug = "test-candidate"
    return f"""---
id: {record_id}
kind: gotcha
status: active
slug: {slug}
title: {title}
created: {created}
author: tests/unit
scope: [memory/**]
tags: [test]
aliases: [写入路径样例]
confidence: low
review_after: 2027-01-01
evidence:
  - file:README.md
check:
  - path_exists:memory/tools/memory.py
---

## 内容

这是测试用的候选记录，用来验证 propose 预检、spool 写入与 drain 搬运，不会进入正式语料。
它刻意与已有记录保持不同词汇，避免触发近重复检查（测试里另有专门用例制造近重复）。

## 为什么

写入路径是记忆库最容易出竞态的地方，必须用测试钉住：候选只进 `.spool/`，`drain` 才进 `records/`。

## 用法

`propose --write` → `drain` → `validate`，三步都应有可观察输出。
"""


class TestFrontmatter(unittest.TestCase):
    def test_parse_basic(self):
        data, body = TOOL_MODULE.parse_frontmatter(_candidate())
        self.assertEqual(data["id"], "mem-20260101-9001")
        self.assertEqual(data["scope"], ["memory/**"])
        self.assertEqual(data["tags"], ["test"])
        self.assertIn("## 内容", body)

    def test_inline_list_with_quotes(self):
        self.assertEqual(
            TOOL_MODULE._split_inline_list('[a, "b, c", d]'),
            ["a", "b, c", "d"],
        )

    def test_missing_frontmatter_rejected(self):
        with self.assertRaises(TOOL_MODULE.MemoryError_):
            TOOL_MODULE.parse_frontmatter("没有 frontmatter 的正文")

    def test_unclosed_frontmatter_rejected(self):
        with self.assertRaises(TOOL_MODULE.MemoryError_):
            TOOL_MODULE.parse_frontmatter("---\nid: mem-20260101-9001\n")

    def test_cjk_tokens_include_unigram_and_bigram(self):
        tokens = TOOL_MODULE._tokens("插件重启")
        self.assertIn("重", tokens)
        self.assertIn("重启", tokens)

    def test_query_tokens_prefer_strong(self):
        self.assertEqual(TOOL_MODULE._query_tokens("插件重启"), ["插件", "件重", "重启"])


class TestCorpus(unittest.TestCase):
    def setUp(self):
        self.records = TOOL_MODULE.load_records(MEMORY_ROOT)

    def test_corpus_not_empty(self):
        self.assertGreaterEqual(len(self.records), 10)

    def test_validate_clean(self):
        errors, _warnings = TOOL_MODULE.validate_records(self.records, ROOT)
        self.assertEqual(errors, [])

    def test_ids_unique(self):
        ids = [record.id for record in self.records]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_record_has_three_sections(self):
        for record in self.records:
            self.assertIn("## 内容", record.body, record.path.name)
            self.assertIn("## 为什么", record.body, record.path.name)
            self.assertIn("## 用法", record.body, record.path.name)

    def test_supersede_chain_consistent(self):
        by_id = {record.id: record for record in self.records}
        for record in self.records:
            for target_id in record.supersedes:
                self.assertIn(target_id, by_id)
                self.assertEqual(by_id[target_id].status, "superseded")
                self.assertEqual(by_id[target_id].data.get("superseded_by"), record.id)

    def test_core_within_budget(self):
        result = _run(["core", "--budget", "1200"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("核心记忆", result.stdout)


@unittest.skipUnless(HAS_FTS5, "当前 Python 的 sqlite3 没有 FTS5")
class TestSearch(unittest.TestCase):
    def setUp(self):
        self.searcher = TOOL_MODULE.Searcher(TOOL_MODULE.load_records(MEMORY_ROOT))

    def test_exact_id_hit(self):
        results = self.searcher.search("mem-20261019-0003", limit=1)
        self.assertEqual(results[0]["id"], "mem-20261019-0003")

    def test_gotcha_query(self):
        results = self.searcher.search("插件改完为什么不生效", limit=3)
        self.assertEqual(results[0]["id"], "mem-20261019-0003")

    def test_scope_filter_and_scope_miss_marking(self):
        results = self.searcher.search(
            "工具数量", touched=["integrations/dsh-sysml-viz/client.js"], limit=3,
        )
        self.assertTrue(results)
        self.assertTrue(all("scopeMiss" in item for item in results))

    def test_status_filter_excludes_superseded(self):
        results = self.searcher.search("工具数", statuses=["active"], limit=5)
        self.assertNotIn("mem-20261017-0011", [item["id"] for item in results])

    def test_eval_dev_threshold(self):
        cases = json.loads((MEMORY_ROOT / "eval" / "queries.json").read_text(encoding="utf-8"))
        metrics = TOOL_MODULE._eval_set(self.searcher, cases)
        self.assertGreaterEqual(metrics["recall@1"], 0.9, metrics)

    def test_eval_heldout_threshold(self):
        cases = json.loads((MEMORY_ROOT / "eval" / "heldout.json").read_text(encoding="utf-8"))
        metrics = TOOL_MODULE._eval_set(self.searcher, cases)
        self.assertGreaterEqual(metrics["mrr"], 0.8, metrics)


class TestTrust(unittest.TestCase):
    def test_inject_wraps_untrusted_nonre(self):
        result = _run(["inject", "插件改完不生效", "--budget", "400"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<untrusted-memory nonce=", result.stdout)
        self.assertIn("数据", result.stdout)
        self.assertIn("未验证", result.stdout)

    def test_core_over_budget_fails_fast(self):
        result = _run(["core", "--budget", "100"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("超过整块预算", result.stderr)

    def test_check_clean(self):
        result = _run(["check"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestWritePath(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="sysml-memory-test-"))
        self.memory_copy = self.temp_dir / "memory"
        shutil.copytree(MEMORY_ROOT, self.memory_copy)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_propose_dry_run_writes_nothing(self):
        candidate = self.temp_dir / "candidate.md"
        candidate.write_text(_candidate(), encoding="utf-8")
        result = _run(["propose", "--from-file", str(candidate)], memory_root=self.memory_copy)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dry-run", result.stdout)
        spool = self.memory_copy / ".spool"
        self.assertFalse(spool.exists() and any(spool.glob("*.md")))

    def test_propose_write_then_drain(self):
        candidate = self.temp_dir / "candidate.md"
        candidate.write_text(_candidate(), encoding="utf-8")
        write = _run(["propose", "--from-file", str(candidate), "--write"], memory_root=self.memory_copy)
        self.assertEqual(write.returncode, 0, write.stdout + write.stderr)
        self.assertTrue(any((self.memory_copy / ".spool").glob("*.md")))
        drain = _run(["drain"], memory_root=self.memory_copy)
        self.assertEqual(drain.returncode, 0, drain.stdout + drain.stderr)
        self.assertIn("mem-20260101-9001", drain.stdout)
        self.assertTrue(any((self.memory_copy / "records").rglob("mem-20260101-9001-*.md")))
        validate = _run(["validate"], memory_root=self.memory_copy)
        self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)

    def test_duplicate_id_rejected(self):
        candidate = self.temp_dir / "candidate.md"
        candidate.write_text(_candidate(record_id="mem-20261019-0003"), encoding="utf-8")
        result = _run(["propose", "--from-file", str(candidate)], memory_root=self.memory_copy)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("E-PROPOSE-ID-DUP", result.stdout)

    def test_future_created_rejected(self):
        candidate = self.temp_dir / "candidate.md"
        candidate.write_text(_candidate(created="2099-01-01T10:00:00+08:00"), encoding="utf-8")
        result = _run(["propose", "--from-file", str(candidate)], memory_root=self.memory_copy)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("E-CREATED-FUTURE", result.stdout)

    def test_near_duplicate_rejected(self):
        existing = next((MEMORY_ROOT / "records").rglob("mem-20261019-0003-*.md"))
        text = existing.read_text(encoding="utf-8")
        text = text.replace("id: mem-20261019-0003", "id: mem-20260101-9002")
        text = text.replace("created: 2026-10-19T23:40:00+08:00", "created: 2026-01-01T10:00:00+08:00")
        text = text.replace("slug: plugin-restart", "slug: near-dup")
        candidate = self.temp_dir / "candidate.md"
        candidate.write_text(text, encoding="utf-8")
        result = _run(["propose", "--from-file", str(candidate)], memory_root=self.memory_copy)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("E-PROPOSE-NEAR-DUP", result.stdout)


if __name__ == "__main__":
    unittest.main()
