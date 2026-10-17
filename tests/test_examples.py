"""T5 —— 标杆案例（T4）与仓库布局的自洽性。

这些用例把「仓库里的产物」钉住：IR 必须通过校验、存档的 .sysml 必须与生成器
逐字节一致、一页说明必须在。任何手工改动产物都会在这里被抓住。
"""

from __future__ import annotations

import json
import unittest

from _support import (
    GOLDEN_DIR,
    GOLDEN_IR,
    GOLDEN_SYSML,
    REPO_ROOT,
    generate_sysml,
    golden_model,
    load_model,
    query_model,
    roundtrip_check,
    validate_model_json,
)


class TestGoldenArtifacts(unittest.TestCase):
    def test_golden_ir_exists_and_is_valid_json(self):
        self.assertTrue(GOLDEN_IR.is_file())
        self.assertEqual(load_model(GOLDEN_IR)["schema"], "sysml-ir/v1")

    def test_golden_ir_passes_validation_with_zero_errors_and_warnings(self):
        result = validate_model_json(golden_model())
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [], msg=result["warnings"])

    def test_checked_in_sysml_matches_generated_output(self):
        """存档文件必须与生成器输出逐字节一致（防止手工改产物造成漂移）。"""
        self.assertTrue(GOLDEN_SYSML.is_file())
        result = generate_sysml(golden_model())
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertEqual(result["text"], GOLDEN_SYSML.read_text(encoding="utf-8"))

    def test_generation_is_deterministic_twice(self):
        first = generate_sysml(golden_model())
        second = generate_sysml(golden_model())
        self.assertEqual(first["sha256"], second["sha256"])

    def test_golden_sysml_passes_roundtrip_verification(self):
        check = roundtrip_check(golden_model(), GOLDEN_SYSML.read_text(encoding="utf-8"))
        self.assertTrue(check["ok"], msg=json.dumps(check, ensure_ascii=False)[:1500])

    def test_golden_has_no_unsatisfied_requirement(self):
        result = query_model(golden_model(), unsatisfied_requirements=True)
        self.assertEqual(result["count"], 0, msg=result["results"])

    def test_golden_covers_all_six_kinds_except_behavior(self):
        """T4 约定：需求 + 结构 + 参数齐全；行为（StateDefinition）留空位给二期。"""
        kinds = {e["kind"] for e in golden_model()["elements"]}
        self.assertIn("Requirement", kinds)
        self.assertIn("PartDefinition", kinds)
        self.assertIn("PartUsage", kinds)
        self.assertIn("Attribute", kinds)
        self.assertIn("ActionDefinition", kinds)
        self.assertNotIn("StateDefinition", kinds)

    def test_golden_power_chain_is_complete(self):
        """电池 → 电调 → 电机 → 桨（含上下桨）四级都在，且用 connects 串起来。"""
        model = golden_model()
        ids = {e["id"] for e in model["elements"]}
        for required in (
            "PART-BATTERY-PACK",
            "PART-ESC",
            "PART-MOTOR",
            "PART-PROP-UPPER",
            "PART-PROP-LOWER",
        ):
            self.assertIn(required, ids)
        connects = [
            r
            for e in model["elements"]
            for r in (e.get("relations") or [])
            if r.get("type") == "connects"
        ]
        self.assertGreaterEqual(len(connects), 4, msg="功率链连接关系太少：%s" % connects)

    def test_golden_readme_exists(self):
        """T4 要求「IR + 生成的 SysML v2 文本 + 一页说明」。"""
        readme = GOLDEN_DIR / "README.md"
        self.assertTrue(readme.is_file())


class TestRepositoryLayout(unittest.TestCase):
    """技术方案 8.4 约定的目录结构必须齐全。"""

    def test_expected_directories_exist(self):
        for relative in (
            "skills",
            "mcp-server",
            "mcp-server/tools",
            "mcp-server/schema",
            "knowledge",
            "examples",
            "tests",
            "docs",
        ):
            self.assertTrue((REPO_ROOT / relative).is_dir(), msg="缺少目录：%s" % relative)

    def test_expected_toplevel_files_exist(self):
        for relative in ("install.sh", "README.md", "mcp-server/run_server.py",
                         "mcp-server/requirements.txt",
                         "mcp-server/schema/sysml-ir-v1.json",
                         "mcp-server/schema/字段说明.md"):
            self.assertTrue((REPO_ROOT / relative).is_file(), msg="缺少文件：%s" % relative)

    def test_three_skills_have_skill_md(self):
        for name in ("modeling-workflow", "element-choice", "anti-patterns"):
            path = REPO_ROOT / "skills" / name / "SKILL.md"
            self.assertTrue(path.is_file(), msg="缺少 skill：%s" % path)
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---"), msg="%s 缺少 YAML frontmatter" % name)
            self.assertIn("name:", text.split("---")[1])
            self.assertIn("description:", text.split("---")[1])

    def test_docs_exist(self):
        for relative in ("docs/T0-调研结论.md", "docs/T6-演示记录.md"):
            self.assertTrue((REPO_ROOT / relative).is_file(), msg="缺少文档：%s" % relative)

    def test_no_macos_specific_absolute_paths_in_source(self):
        """跨平台要求：源码里不得出现 /Users/ 之类硬编码系统路径。"""
        offenders = []
        for path in (REPO_ROOT / "mcp-server").rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                    continue
                for marker in ('"/Users/', "'/Users/", '"/Applications/', "'/Applications/",
                               '"C:\\\\', "'C:\\\\"):
                    if marker in line:
                        offenders.append("%s:%d %s" % (path.name, number, stripped[:80]))
        self.assertEqual(offenders, [], msg="发现硬编码系统路径：%s" % offenders)


if __name__ == "__main__":
    unittest.main(verbosity=2)
