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
    element,
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

    def test_golden_covers_all_eight_kinds_including_behavior(self):
        """T4 + v1 增补 + 二期：8 种 kind 全齐（含行为 StateDefinition，恰好 1 个）。"""
        kinds = {e["kind"] for e in golden_model()["elements"]}
        self.assertIn("Requirement", kinds)
        self.assertIn("PartDefinition", kinds)
        self.assertIn("PartUsage", kinds)
        self.assertIn("Attribute", kinds)
        self.assertIn("ActionDefinition", kinds)
        self.assertIn("Constraint", kinds)
        self.assertIn("Connection", kinds)
        self.assertIn("StateDefinition", kinds)
        states = [e for e in golden_model()["elements"] if e["kind"] == "StateDefinition"]
        self.assertEqual(len(states), 1, msg="行为元素应恰好 1 个")

    def test_golden_state_machine_follows_antipattern_16(self):
        """行为元素的形态：初始态出边不挂 trigger/guard，事件迁移从非初始态出发。"""
        state = [e for e in golden_model()["elements"] if e["kind"] == "StateDefinition"][0]
        props = state["properties"]
        states = props["states"]
        initial = props["initial"]
        self.assertIn(initial, states)
        self.assertGreaterEqual(len(states), 4, msg="状态数太少：%s" % states)
        self.assertGreaterEqual(len(props["transitions"]), 4)
        for index, transition in enumerate(props["transitions"]):
            self.assertIn(transition["from"], states)
            self.assertIn(transition["to"], states)
            if transition["from"] == initial:
                self.assertNotIn("trigger", transition, msg="初始态出边不得挂 trigger")
                self.assertNotIn("guard", transition, msg="初始态出边不得挂 guard")
            else:
                self.assertTrue(
                    transition.get("trigger") or transition.get("guard"),
                    msg="非初始态迁移 %d 至少要有 trigger 或 guard" % index,
                )

    def test_golden_state_machine_guard_uses_formal_if(self):
        """guard 走正式 `if (...)` 语句，而不是注释。"""
        text = GOLDEN_SYSML.read_text(encoding="utf-8")
        self.assertIn("state def FlightModeStates {", text)
        self.assertIn("entry; then Takeoff;", text)
        self.assertRegex(text, r"transition \w+ first Cruise if \([^)]*\) then Fault;")

    def test_golden_includes_constraint_demo(self):
        """Constraint 示范：续航换算公式 + 参数全部指向已有 Attribute。"""
        model = golden_model()
        constraint = element(model, "CONSTRAINT-ENDURANCE-BUDGET")
        self.assertEqual(constraint["kind"], "Constraint")
        self.assertIn("cruisePowerW", constraint["properties"]["expression"])
        attributes = {
            e["id"] for e in model["elements"] if e["kind"] == "Attribute"
        }
        self.assertTrue(constraint["properties"]["parameters"])
        for parameter in constraint["properties"]["parameters"]:
            self.assertIn(parameter, attributes)

    def test_golden_includes_connection_demo(self):
        """Connection 示范：电池→电调（electrical）、上桨电机→上桨（mechanical）。"""
        model = golden_model()
        connections = [e for e in model["elements"] if e["kind"] == "Connection"]
        self.assertEqual(len(connections), 2)
        flows = {c["properties"]["flowKind"] for c in connections}
        self.assertEqual(flows, {"electrical", "mechanical"})
        text = GOLDEN_SYSML.read_text(encoding="utf-8")
        self.assertIn("connect batteryPack to escUnit;", text)
        self.assertIn("connect upperMotor to upperPropeller;", text)

    def test_golden_readme_counts_match_ir(self):
        """README 的元素/关系计数必须与 IR 实际一致（防止增补后文档漂移）。"""
        model = golden_model()
        elements = len(model["elements"])
        relations = sum(len(e.get("relations") or []) for e in model["elements"])
        readme = (GOLDEN_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("%d 个元素" % elements, readme)
        self.assertIn("%d 条关系" % relations, readme)
        self.assertIn("%d/%d 元素匹配" % (elements, elements), readme)

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
