"""``tools.timeline`` 的契约测试（``sysml-timeline/v1`` + ``sysml-viz-history/v1``）。

全部 fixture 用 ``tempfile.TemporaryDirectory`` 现造：一个 4 步历史

- 第 0 步：基线 1 个 Attribute；
- 第 1 步：+一个 Requirement；
- 第 2 步：+PartDefinition / PartUsage，并修改基线 Attribute 的属性；
- 第 3 步：+一个 Attribute。

覆盖：导出产物、summary / firstSeen、步骤颜色与节点颜色一致、基线灰色、修改标注、
确定性、CLI（``--check`` / 默认输出 / ``--json``）、缺 index / 坏 JSON / 缺快照 /
坏快照 / 空 steps / 写失败、``build_timeline`` 不修改入参、成环 owner 挂根、
无外部引用与 XML 可解析。

不使用 pytest；只用标准库 ``unittest``。所有生成时间都固定传入，不依赖网络/时区。
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

from _support import MCP_SERVER, REPO_ROOT

from tools.timeline import (
    BASELINE_COLOR,
    HISTORY_SCHEMA,
    TIMELINE_SCHEMA,
    TimelineError,
    build_timeline,
    export_timeline,
    load_history,
    render_svg,
)

TIMELINE_PY = MCP_SERVER / "tools" / "timeline.py"

PACKAGE = "Demo"
SESSION = "8e56d6b9"
FIXED_GEN = "2026-10-19T13:00:00.000Z"
AT = (
    "2026-10-19T12:40:00.000Z",
    "2026-10-19T12:44:00.000Z",
    "2026-10-19T12:47:00.000Z",
    "2026-10-19T12:49:30.000Z",
)
REVISIONS = ("0a1b2c3d", "1a2b3c4d", "2b3c4d5e", "3c4d5e6f")

STEP_KEYS = {
    "seq",
    "at",
    "revision",
    "sessionId",
    "elements",
    "relations",
    "added",
    "removed",
    "changed",
    "source",
    "color",
    "label",
    "turn",
    "note",
}
ELEMENT_KEYS = {
    "id",
    "name",
    "kind",
    "owner",
    "firstSeq",
    "lastSeq",
    "changedSeqs",
    "color",
}
SUMMARY_KEYS = {
    "steps",
    "elements",
    "relations",
    "firstAt",
    "lastAt",
    "addedByStep",
    "changedCount",
    "removedCount",
}


# --------------------------------------------------------------------------------------
# Fixture
# --------------------------------------------------------------------------------------


def _baseline(value: float = 12.0) -> Dict[str, Any]:
    return {
        "id": "ATTR-BATTERY-ENERGY",
        "kind": "Attribute",
        "name": "batteryEnergyWh",
        "owner": PACKAGE,
        "properties": {"valueType": "Real", "defaultValue": value, "unit": "kWh"},
    }


def _requirement() -> Dict[str, Any]:
    return {
        "id": "REQ-CRUISE-ENDURANCE",
        "kind": "Requirement",
        "name": "CruiseEndurance",
        "owner": PACKAGE,
        "properties": {"text": "巡航续航不低于 4 h。", "minEnduranceHours": 4.0},
    }


def _part_definition() -> Dict[str, Any]:
    return {
        "id": "PART-DEF-MOTOR",
        "kind": "PartDefinition",
        "name": "BrushlessMotor",
        "owner": PACKAGE,
        "properties": {"description": "无刷电机。"},
    }


def _part_usage() -> Dict[str, Any]:
    return {
        "id": "PART-USE-MOTOR",
        "kind": "PartUsage",
        "name": "motorOne",
        "owner": "PART-DEF-MOTOR",
        "properties": {"typeRef": "PART-DEF-MOTOR", "quantity": 2},
    }


def _cruise_speed() -> Dict[str, Any]:
    return {
        "id": "ATTR-CRUISE-SPEED",
        "kind": "Attribute",
        "name": "cruiseSpeed",
        "owner": "PART-DEF-MOTOR",
        "properties": {"valueType": "Real", "defaultValue": 14.0, "unit": "m/s"},
    }


def fixture_models() -> List[Dict[str, Any]]:
    """4 个完整 IR：基线 1 → +需求 → +两个 Part +改基线属性 → +属性。"""
    base = _baseline()
    changed = _baseline(24.0)
    return [
        {"schema": "sysml-ir/v1", "package": PACKAGE, "meta": {}, "elements": [copy.deepcopy(base)]},
        {
            "schema": "sysml-ir/v1",
            "package": PACKAGE,
            "meta": {},
            "elements": [copy.deepcopy(base), _requirement()],
        },
        {
            "schema": "sysml-ir/v1",
            "package": PACKAGE,
            "meta": {},
            "elements": [
                copy.deepcopy(changed),
                _requirement(),
                _part_definition(),
                _part_usage(),
            ],
        },
        {
            "schema": "sysml-ir/v1",
            "package": PACKAGE,
            "meta": {},
            "elements": [
                copy.deepcopy(changed),
                _requirement(),
                _part_definition(),
                _part_usage(),
                _cruise_speed(),
            ],
        },
    ]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_history(root: Path, models: List[Dict[str, Any]]) -> Path:
    """按插件格式写 index + 逐级快照；返回历史目录。"""
    history_dir = root / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    previous: Dict[str, Dict[str, Any]] = {}
    steps: List[Dict[str, Any]] = []
    for seq, model in enumerate(models):
        elements = [
            item
            for item in model.get("elements", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        current = {item["id"]: item for item in elements}
        added = [] if seq == 0 else [item["id"] for item in elements if item["id"] not in previous]
        removed = [element_id for element_id in previous if element_id not in current]
        changed = [
            item["id"]
            for item in elements
            if item["id"] in previous and item != previous[item["id"]]
        ]
        revision = REVISIONS[seq % len(REVISIONS)]
        snapshot = "step-%04d-%s.ir.json" % (seq, revision)
        (history_dir / snapshot).write_text(
            json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        digest = hashlib.sha256(canonical_json(model).encode("utf-8")).hexdigest()
        steps.append(
            {
                "seq": seq,
                "at": AT[seq % len(AT)],
                "revision": revision,
                "irSha256": digest,
                "semanticSha256": digest,
                "elements": len(elements),
                "relations": sum(len(item.get("relations") or []) for item in elements),
                "added": added,
                "removed": removed,
                "changed": changed,
                "source": "baseline" if seq == 0 else "change",
                "sessionId": SESSION,
                "snapshot": snapshot,
            }
        )
        previous = current

    index = {
        "schema": HISTORY_SCHEMA,
        "workspace": str(root),
        "modelPath": str(root / "model.ir.json"),
        "createdAt": "2026-10-19T12:39:00.000Z",
        "updatedAt": steps[-1]["at"] if steps else None,
        "steps": steps,
    }
    (history_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return history_dir


def read_snapshots(history_dir: Path, history: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    snapshots: Dict[int, Dict[str, Any]] = {}
    for step in history.get("steps") or []:
        snapshot = step.get("snapshot")
        if not isinstance(snapshot, str):
            continue
        path = Path(snapshot)
        if not path.is_absolute():
            path = history_dir / path
        if not path.is_file():
            continue
        try:
            snapshots[step["seq"]] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return snapshots


def snapshot_path(history_dir: Path, history: Dict[str, Any], seq: int) -> Path:
    for step in history["steps"]:
        if step["seq"] == seq:
            return history_dir / step["snapshot"]
    raise AssertionError("没有第 %d 步快照" % seq)


def codes(items: List[Dict[str, Any]]) -> List[str]:
    return [item["code"] for item in items]


def element_group(svg: str, element_id: str) -> str:
    marker = 'data-id="%s"' % element_id
    start = svg.find(marker)
    if start < 0:
        raise AssertionError("SVG 里找不到元素 %s" % element_id)
    end = svg.find("</g>", start)
    if end < 0:
        raise AssertionError("元素 %s 的 <g> 没有闭合" % element_id)
    return svg[start:end]


class TimelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.root = Path(self._tmpdir.name)
        self.history_dir = write_history(self.root, fixture_models())
        self.history = load_history(self.history_dir)
        self.snapshots = read_snapshots(self.history_dir, self.history)

    def timeline(self) -> Dict[str, Any]:
        history = load_history(self.history_dir)
        return build_timeline(history, read_snapshots(self.history_dir, history))

    def export(self, out_path: Any = None, **kwargs: Any) -> Dict[str, Any]:
        generated_at = kwargs.pop("generated_at", FIXED_GEN)
        return export_timeline(self.history_dir, out_path, generated_at=generated_at, **kwargs)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TIMELINE_PY), *args],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
        )


# --------------------------------------------------------------------------------------
# 导出 / 数据
# --------------------------------------------------------------------------------------


class TestExportAndSummary(TimelineTestCase):
    def test_export_ok_and_svg_file(self) -> None:
        payload = self.export()
        self.assertTrue(payload["ok"], msg=payload["errors"])
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["schema"], TIMELINE_SCHEMA)
        self.assertEqual(payload["schema"], "sysml-timeline/v1")
        self.assertEqual(payload["warnings"], [])
        path = Path(payload["svgPath"])
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<?xml"), msg=text[:80])
        self.assertIn("<svg", text[:500])
        self.assertTrue(text.rstrip().endswith("</svg>"))

    def test_summary_and_step_counts(self) -> None:
        payload = self.export()
        summary = payload["summary"]
        self.assertEqual(set(summary), SUMMARY_KEYS)
        self.assertEqual(summary["steps"], 4)
        self.assertEqual(summary["elements"], 5)
        self.assertEqual(summary["relations"], 0)
        self.assertEqual(summary["firstAt"], AT[0])
        self.assertEqual(summary["lastAt"], AT[3])
        self.assertEqual([item["count"] for item in summary["addedByStep"]], [0, 1, 2, 1])
        self.assertEqual(summary["addedByStep"][2]["ids"], ["PART-DEF-MOTOR", "PART-USE-MOTOR"])
        self.assertEqual(summary["changedCount"], 1)
        self.assertEqual(summary["removedCount"], 0)

        self.assertEqual(len(payload["steps"]), 4)
        self.assertEqual([step["seq"] for step in payload["steps"]], [0, 1, 2, 3])
        self.assertEqual([step["elements"] for step in payload["steps"]], [1, 2, 4, 5])
        self.assertEqual([step["source"] for step in payload["steps"]], ["baseline", "change", "change", "change"])
        self.assertEqual(payload["steps"][2]["changed"], ["ATTR-BATTERY-ENERGY"])
        for step in payload["steps"]:
            self.assertEqual(set(step), STEP_KEYS)

    def test_first_seen_and_element_order(self) -> None:
        timeline = self.timeline()
        self.assertEqual(
            timeline["firstSeen"],
            {
                "PART-DEF-MOTOR": 2,
                "PART-USE-MOTOR": 2,
                "REQ-CRUISE-ENDURANCE": 1,
                "ATTR-BATTERY-ENERGY": 0,
                "ATTR-CRUISE-SPEED": 3,
            },
        )
        self.assertEqual(
            [element["id"] for element in timeline["elements"]],
            [
                "PART-DEF-MOTOR",
                "PART-USE-MOTOR",
                "REQ-CRUISE-ENDURANCE",
                "ATTR-BATTERY-ENERGY",
                "ATTR-CRUISE-SPEED",
            ],
        )
        for element in timeline["elements"]:
            self.assertEqual(set(element), ELEMENT_KEYS)
        self.assertEqual(timeline["colors"], ["#94a3b8", "#3b82f6", "#f59e0b", "#10b981"])
        self.assertEqual([step["color"] for step in timeline["steps"]], timeline["colors"])
        self.assertEqual(timeline["elements"][3]["changedSeqs"], [2])
        self.assertEqual(timeline["elements"][3]["lastSeq"], 2)

    def test_tree_owner_hierarchy(self) -> None:
        tree = self.timeline()["tree"]
        self.assertEqual(tree["id"], PACKAGE)
        self.assertEqual([child["id"] for child in tree["children"]], [
            "PART-DEF-MOTOR",
            "REQ-CRUISE-ENDURANCE",
            "ATTR-BATTERY-ENERGY",
        ])
        motor = tree["children"][0]
        self.assertEqual([child["id"] for child in motor["children"]], [
            "PART-USE-MOTOR",
            "ATTR-CRUISE-SPEED",
        ])
        self.assertEqual(motor["children"][1]["parent"], "PART-DEF-MOTOR")


# --------------------------------------------------------------------------------------
# SVG 内容
# --------------------------------------------------------------------------------------


class TestSvgContent(TimelineTestCase):
    def test_node_color_matches_step_color(self) -> None:
        timeline = self.timeline()
        svg = render_svg(timeline, {"generated_at": FIXED_GEN})
        requirement_color = timeline["steps"][1]["color"]
        group = element_group(svg, "REQ-CRUISE-ENDURANCE")
        self.assertIn('fill="%s"' % requirement_color, group)
        self.assertIn(">CruiseEndurance<", group)
        self.assertIn('fill="%s"' % requirement_color, svg)

    def test_baseline_element_is_gray(self) -> None:
        timeline = self.timeline()
        baseline = [
            element for element in timeline["elements"] if element["id"] == "ATTR-BATTERY-ENERGY"
        ][0]
        self.assertEqual(baseline["color"], BASELINE_COLOR)
        svg = render_svg(timeline, {"generated_at": FIXED_GEN})
        group = element_group(svg, "ATTR-BATTERY-ENERGY")
        self.assertIn('fill="%s"' % BASELINE_COLOR, group)
        self.assertIn("基线 · 已有 1 个元素", svg)

    def test_changed_element_has_triangle_and_outline(self) -> None:
        timeline = self.timeline()
        svg = render_svg(timeline, {"generated_at": FIXED_GEN})
        change_color = timeline["steps"][2]["color"]
        group = element_group(svg, "ATTR-BATTERY-ENERGY")
        self.assertIn("△2", group)
        self.assertIn('stroke="%s"' % change_color, group)
        self.assertIn("第2步修改", group)

    def test_render_is_byte_deterministic(self) -> None:
        timeline = self.timeline()
        first = render_svg(timeline, {"generated_at": FIXED_GEN, "width": 1440})
        second = render_svg(timeline, {"generated_at": FIXED_GEN, "width": 1440})
        self.assertEqual(first, second)

        out_one = self.root / "one.svg"
        out_two = self.root / "two.svg"
        first_export = self.export(out_one)
        second_export = self.export(out_two)
        self.assertTrue(first_export["ok"], msg=first_export["errors"])
        self.assertTrue(second_export["ok"], msg=second_export["errors"])
        self.assertEqual(out_one.read_bytes(), out_two.read_bytes())

    def test_header_width_and_schema(self) -> None:
        timeline = self.timeline()
        svg = render_svg(timeline, {"generated_at": FIXED_GEN})
        self.assertIn('width="1280"', svg)
        self.assertIn("建模全过程 · Demo", svg)
        self.assertIn("4 步 · 5 元素 · 0 关系", svg)
        self.assertIn("生成时间", svg)
        self.assertIn(TIMELINE_SCHEMA, svg)
        wide = render_svg(timeline, {"generated_at": FIXED_GEN, "width": "1600"})
        self.assertIn('width="1600"', wide)

    def test_no_external_references_and_parsable_xml(self) -> None:
        svg = render_svg(self.timeline(), {"generated_at": FIXED_GEN})
        for token in ("http://", "https://", "<image", "href=", "<script"):
            self.assertNotIn(token, svg)
        root = ET.fromstring(svg.encode("utf-8"))
        self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
        self.assertEqual(root.get("width"), "1280")
        self.assertIsNotNone(root.get("height"))


# --------------------------------------------------------------------------------------
# 降级 / 错误
# --------------------------------------------------------------------------------------


class TestDegradationAndErrors(TimelineTestCase):
    def test_missing_index_is_not_found(self) -> None:
        missing = self.root / "no-such-history"
        payload = export_timeline(missing, generated_at=FIXED_GEN)
        self.assertFalse(payload["ok"])
        self.assertEqual(codes(payload["errors"]), ["E-HISTORY-NOT-FOUND"])

        empty_dir = self.root / "empty-history"
        empty_dir.mkdir()
        payload = export_timeline(empty_dir, generated_at=FIXED_GEN)
        self.assertFalse(payload["ok"])
        self.assertEqual(codes(payload["errors"]), ["E-HISTORY-NOT-FOUND"])

        with self.assertRaises(TimelineError) as caught:
            load_history(missing)
        self.assertEqual(caught.exception.code, "E-HISTORY-NOT-FOUND")
        self.assertTrue(caught.exception.message)

    def test_bad_json_index_is_schema_error(self) -> None:
        (self.history_dir / "index.json").write_text("{not valid json", encoding="utf-8")
        payload = self.export()
        self.assertFalse(payload["ok"])
        self.assertEqual(codes(payload["errors"]), ["E-HISTORY-SCHEMA"])
        self.assertEqual(payload["steps"], [])

    def test_missing_snapshot_degrades_with_warning(self) -> None:
        snapshot_path(self.history_dir, self.history, 1).unlink()
        payload = self.export()
        self.assertTrue(payload["ok"], msg=payload["errors"])
        self.assertIn("W-SNAPSHOT-MISSING", codes(payload["warnings"]))
        self.assertEqual(payload["summary"]["elements"], 5)
        svg = Path(payload["svgPath"]).read_text(encoding="utf-8")
        self.assertIn("个快照缺失", svg)
        self.assertIn("CruiseEndurance", svg)

    def test_broken_snapshot_uses_previous_valid_snapshot(self) -> None:
        last = snapshot_path(self.history_dir, self.history, 3)
        last.write_text(
            json.dumps({"schema": "sysml-ir/v1", "package": PACKAGE}) + "\n",
            encoding="utf-8",
        )
        payload = self.export()
        self.assertTrue(payload["ok"], msg=payload["errors"])
        self.assertIn("W-SNAPSHOT-PARSE", codes(payload["warnings"]))
        # 最终树跟随最后一个有效快照（第 2 步，4 个元素），而不是 index 元数据的 5。
        self.assertEqual(payload["summary"]["elements"], 4)
        timeline = build_timeline(
            load_history(self.history_dir),
            read_snapshots(self.history_dir, load_history(self.history_dir)),
        )
        self.assertNotIn("ATTR-CRUISE-SPEED", timeline["firstSeen"])

    def test_empty_steps_is_no_steps(self) -> None:
        index_path = self.history_dir / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["steps"] = []
        index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        payload = self.export()
        self.assertFalse(payload["ok"])
        self.assertEqual(codes(payload["errors"]), ["E-NO-STEPS"])

    def test_seq_gap_is_schema_error(self) -> None:
        index_path = self.history_dir / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["steps"][2]["seq"] = 5
        index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        payload = self.export()
        self.assertFalse(payload["ok"])
        self.assertEqual(codes(payload["errors"]), ["E-HISTORY-SCHEMA"])

    def test_write_failure_reports_e_write(self) -> None:
        payload = self.export(self.root)  # 目标是已存在的目录 → 写文件失败
        self.assertFalse(payload["ok"])
        self.assertEqual(codes(payload["errors"]), ["E-WRITE"])
        self.assertIsNone(payload["svgPath"])
        self.assertEqual(len(payload["steps"]), 4)
        self.assertEqual(payload["summary"]["elements"], 5)


# --------------------------------------------------------------------------------------
# 纯函数 / 边界
# --------------------------------------------------------------------------------------


class TestPureFunctionAndTreeEdges(TimelineTestCase):
    def test_build_timeline_does_not_mutate_inputs(self) -> None:
        history = load_history(self.history_dir)
        snapshots = read_snapshots(self.history_dir, history)
        history_before = copy.deepcopy(history)
        snapshots_before = copy.deepcopy(snapshots)
        build_timeline(history, snapshots)
        self.assertEqual(history, history_before)
        self.assertEqual(snapshots, snapshots_before)

    def test_cycle_and_orphan_owner_attach_to_root(self) -> None:
        model = {
            "schema": "sysml-ir/v1",
            "package": PACKAGE,
            "elements": [
                {"id": "CYCLE-A", "kind": "PartDefinition", "name": "A", "owner": "CYCLE-B", "properties": {}},
                {"id": "CYCLE-B", "kind": "PartUsage", "name": "B", "owner": "CYCLE-A", "properties": {}},
                {"id": "ORPHAN-C", "kind": "Requirement", "name": "C", "owner": "Ghost", "properties": {}},
                {"id": "ROOT-D", "kind": "Attribute", "name": "D", "owner": PACKAGE, "properties": {}},
            ],
        }
        history = {
            "schema": HISTORY_SCHEMA,
            "steps": [
                {
                    "seq": 0,
                    "at": AT[0],
                    "revision": "deadbeef",
                    "source": "baseline",
                    "added": [],
                    "removed": [],
                    "changed": [],
                    "elements": 4,
                    "relations": 0,
                    "sessionId": None,
                    "snapshot": "unused.ir.json",
                }
            ],
        }
        timeline = build_timeline(history, {0: model})
        root_ids = [child["id"] for child in timeline["tree"]["children"]]
        self.assertEqual(root_ids, ["CYCLE-A", "CYCLE-B", "ORPHAN-C", "ROOT-D"])
        for child in timeline["tree"]["children"]:
            self.assertEqual(child["parent"], PACKAGE)
        self.assertEqual(timeline["summary"]["elements"], 4)
        self.assertEqual(timeline["colors"], [BASELINE_COLOR])

    def test_optional_turn_and_note_are_passed_through(self) -> None:
        """真实 session-log 历史里的可选 turn/note 不破坏契约字段。"""
        history = load_history(self.history_dir)
        history["steps"] = history["steps"][:2]
        history["steps"][1]["source"] = "session-log"
        history["steps"][1]["turn"] = 2
        history["steps"][1]["note"] = "第 2 轮结束时写入"
        timeline = build_timeline(
            history,
            {0: self.snapshots[0], 1: self.snapshots[1]},
        )
        step = timeline["steps"][1]
        self.assertEqual(step["turn"], 2)
        self.assertEqual(step["note"], "第 2 轮结束时写入")
        self.assertEqual(step["label"], "第 2 轮")
        svg = render_svg(timeline, {"generated_at": FIXED_GEN})
        self.assertIn("第 2 轮", svg)
        self.assertIn("日志重建", svg)

    def test_deep_tree_beyond_eight_levels_renders(self) -> None:
        elements = []
        owner = PACKAGE
        for index in range(12):
            element_id = "N%02d" % index
            elements.append(
                {
                    "id": element_id,
                    "kind": "PartDefinition",
                    "name": "Node%02d" % index,
                    "owner": owner,
                    "properties": {},
                }
            )
            owner = element_id
        model = {"schema": "sysml-ir/v1", "package": PACKAGE, "elements": elements}
        history = {
            "schema": HISTORY_SCHEMA,
            "steps": [
                {
                    "seq": 0,
                    "at": AT[0],
                    "source": "baseline",
                    "added": [],
                    "removed": [],
                    "changed": [],
                    "elements": len(elements),
                    "relations": 0,
                }
            ],
        }
        timeline = build_timeline(history, {0: model})
        self.assertEqual(len(timeline["tree"]["children"]), 1)
        svg = render_svg(timeline, {"generated_at": FIXED_GEN})
        self.assertIn(">Node11<", svg)
        root = ET.fromstring(svg.encode("utf-8"))
        self.assertGreater(int(root.get("height")), 8 * 74)


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


class TestCli(TimelineTestCase):
    def test_check_cli_ok(self) -> None:
        completed = self.run_cli("--history", str(self.history_dir), "--check")
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload, {"ok": True, "steps": 4, "errors": []})

    def test_check_cli_failure_exit_1(self) -> None:
        completed = self.run_cli("--history", str(self.root / "missing"), "--check")
        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(codes(payload["errors"]), ["E-HISTORY-NOT-FOUND"])
        self.assertEqual(payload["steps"], 0)

    def test_cli_default_out_and_json(self) -> None:
        completed = self.run_cli("--history", str(self.history_dir))
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        default_out = self.history_dir / "timeline.svg"
        self.assertTrue(default_out.is_file())
        summary = json.loads(completed.stdout)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"], 4)
        self.assertEqual(summary["elements"], 5)
        self.assertEqual(Path(summary["svgPath"]), default_out)

        custom_out = self.root / "custom.svg"
        completed = self.run_cli(
            "--history", str(self.history_dir), "--out", str(custom_out), "--json"
        )
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"], msg=payload["errors"])
        self.assertEqual(payload["schema"], TIMELINE_SCHEMA)
        self.assertEqual(Path(payload["svgPath"]), custom_out)
        self.assertTrue(custom_out.is_file())
        self.assertEqual(len(payload["steps"]), 4)
        self.assertEqual(payload["summary"]["elements"], 5)

    def test_cli_json_failure_exit_1(self) -> None:
        completed = self.run_cli("--history", str(self.root / "missing"), "--json")
        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(codes(payload["errors"]), ["E-HISTORY-NOT-FOUND"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
