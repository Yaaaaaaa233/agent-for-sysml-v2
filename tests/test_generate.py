"""T5 —— ``generate_sysml`` 的正例、确定性与拒绝行为。"""

from __future__ import annotations

import json
import unittest

from _support import (
    base_model,
    codes,
    edit_element,
    generate_sysml,
    golden_model,
    roundtrip_check,
)


class TestDeterminism(unittest.TestCase):
    """方案 2.4 的「可复现」：同输入必得同输出。"""

    def test_two_runs_are_byte_identical(self):
        model = base_model()
        first = generate_sysml(model)
        second = generate_sysml(model)
        self.assertTrue(first["ok"])
        self.assertEqual(first["text"], second["text"])
        self.assertEqual(first["sha256"], second["sha256"])

    def test_determinism_on_golden_case(self):
        model = golden_model()
        first = generate_sysml(model)
        second = generate_sysml(model)
        self.assertTrue(first["ok"], msg=codes(first))
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["text"], second["text"])

    def test_key_order_does_not_change_output(self):
        """JSON 对象键序变化不该改变输出（渲染按固定 kind 顺序 + id 排序）。"""
        model = base_model()
        shuffled = json.loads(json.dumps(model))
        shuffled["elements"] = list(reversed(shuffled["elements"]))
        self.assertEqual(
            generate_sysml(model)["text"],
            generate_sysml(shuffled)["text"],
        )


class TestRendering(unittest.TestCase):
    """渲染形态：必须覆盖 6 种 kind 与 relations。"""

    def setUp(self):
        self.result = generate_sysml(base_model())
        self.assertTrue(self.result["ok"], msg=codes(self.result))
        self.text = self.result["text"]
        self.lines = self.text.split("\n")

    def test_has_package_header(self):
        self.assertIn("package Demo {", self.lines)
        self.assertTrue(self.text.rstrip().endswith("}"))

    def test_renders_part_definition(self):
        """没有子元素的定义渲染为 `part def X;`（合法且更短）。"""
        self.assertIn("    part def Motor;", self.text)
        self.assertIn("// description: 无刷电机。", self.text)

    def test_renders_part_definition_with_body(self):
        """有子元素的定义必须渲染成带大括号的体。"""
        self.assertIn("    requirement def ReqAlpha {", self.text)
        self.assertIn("    part def Motor;", self.text)
        model = base_model()
        # 把 PartUsage 挂到 PartDefinition 下，制造一个带体的 part def
        for item in model["elements"]:
            if item["id"] == "PART-USE-MOTOR":
                item["owner"] = "PART-DEF-MOTOR"
        text = generate_sysml(model)["text"]
        self.assertIn("    part def Motor {", text)
        self.assertIn("        part motorOne : Motor;", text)

    def test_renders_part_usage_with_resolved_type_name(self):
        """typeRef 渲染成被引用元素的 **name**（Motor），而不是内部 id（PART-DEF-MOTOR）。"""
        self.assertIn("part motorOne : Motor;", self.text)
        self.assertNotIn("PART-DEF-MOTOR", self.text.split("//")[0])

    def test_usage_is_nested_under_owner(self):
        """owner 是元素时，PartUsage 必须缩进渲染在 owner 体内。"""
        model = base_model()
        for item in model["elements"]:
            if item["id"] == "PART-USE-MOTOR":
                item["owner"] = "PART-DEF-MOTOR"
        lines = generate_sysml(model)["text"].split("\n")
        usage = [l for l in lines if "part motorOne : Motor" in l][0]
        self.assertTrue(usage.startswith("        "), msg=usage)
        self.assertIn("    part def Motor {", generate_sysml(model)["text"])

    def test_renders_requirement_def_with_doc_and_criteria(self):
        self.assertIn("    requirement def ReqAlpha {", self.text)
        self.assertIn("doc /* 转速不低于 1000 rpm */", self.text)
        self.assertIn("doc /* 验收判据: 稳态转速 n >= 1000 rpm */", self.text)

    def test_renders_requirement_threshold_as_numeric_attribute(self):
        self.assertIn("attribute minSpeedRpm : Real = 1000.0;", self.text)

    def test_renders_requirement_verify_method(self):
        self.assertIn('attribute verifyMethod : String = "simulation";', self.text)

    def test_renders_action_definition_with_in_and_out(self):
        self.assertIn("    action def ActAlpha {", self.text)
        self.assertIn("in commandRpm : Real;  // unit: rpm", self.text)
        self.assertIn("out measuredRpm : Real;  // unit: rpm", self.text)

    def test_renders_state_definition_states(self):
        self.assertIn("    state def MotorStates {", self.text)
        self.assertIn("state Idle;", self.text)
        self.assertIn("state Running;", self.text)

    def test_renders_state_transitions_as_comment(self):
        """状态迁移在 MVP 以注释承载（不得发明无法验证的语法，见 docs/T0-调研结论.md）。"""
        self.assertIn("// transitions:", self.text)
        self.assertIn("//   Idle --> Running  [trigger: start command]", self.text)

    def test_renders_attribute_with_unit_after_semicolon(self):
        """单位注释必须出现在 `;` 之后，否则语句被注释切断。"""
        line = [l for l in self.lines if "ratedVoltage" in l][0]
        self.assertIn("= 24.0;", line)
        self.assertIn("// unit: V", line)
        self.assertLess(line.index(";"), line.index("// unit:"))

    def test_renders_relations_as_trace_comments(self):
        self.assertIn("// 追溯关系 (relations):", self.text)
        self.assertIn("//   REQ-A --satisfiedBy--> PART-USE-MOTOR  (由电机选型满足)", self.text)

    def test_stats_are_reported(self):
        stats = self.result["stats"]
        self.assertEqual(stats["package"], "Demo")
        self.assertEqual(stats["elements"], len(base_model()["elements"]))
        self.assertEqual(stats["byKind"]["PartDefinition"], 1)
        self.assertEqual(stats["relations"], 2)

    def test_include_header_is_optional(self):
        plain = generate_sysml(base_model(), include_header=False)
        self.assertNotIn("Generated by sysml-modeling-agent", plain["text"])
        self.assertNotEqual(plain["sha256"], self.result["sha256"])

    def test_indent_is_configurable(self):
        two_space = generate_sysml(base_model(), indent="  ")
        self.assertIn("\n  part def Motor;", two_space["text"])
        self.assertIn("\n  // ---- PartDefinition ----", two_space["text"])


class TestRefusal(unittest.TestCase):
    """IR 不合法时必须拒绝渲染，并原样回传错误——让 LLM 改 JSON 而不是改文本。"""

    def test_refuses_model_missing_acceptance_criteria(self):
        model = edit_element(base_model(), "REQ-A", lambda e: e["properties"].pop("acceptanceCriteria"))
        result = generate_sysml(model)
        self.assertFalse(result["ok"])
        self.assertEqual(result["text"], "")
        self.assertIn("E-REQ-NO-ACCEPTANCE", codes(result))

    def test_refuses_dangling_relation_target(self):
        model = edit_element(
            base_model(), "REQ-A", lambda e: e["relations"][0].__setitem__("target", "NOPE")
        )
        result = generate_sysml(model)
        self.assertFalse(result["ok"])
        self.assertIn("E-REL-TARGET-DANGLING", codes(result))

    def test_validate_false_renders_anyway(self):
        """``validate=False`` 是给内部调试用的逃生口，不改变渲染形态。"""
        model = edit_element(base_model(), "REQ-A", lambda e: e["properties"].pop("acceptanceCriteria"))
        result = generate_sysml(model, validate=False)
        self.assertTrue(result["ok"])
        self.assertIn("requirement def ReqAlpha", result["text"])

    def test_result_is_json_serializable(self):
        json.dumps(generate_sysml(base_model()))


class TestGoldenCase(unittest.TestCase):
    """T4 标杆案例的端到端闭环。"""

    def test_golden_generates_and_roundtrips(self):
        model = golden_model()
        result = generate_sysml(model)
        self.assertTrue(result["ok"], msg=codes(result))
        check = roundtrip_check(model, result["text"])
        self.assertTrue(check["ok"], msg=json.dumps(check, ensure_ascii=False)[:1200])
        self.assertEqual(check["counts"]["missing"], 0)
        self.assertEqual(check["counts"]["extra"], 0)
        self.assertEqual(check["counts"]["mismatched"], 0)
        self.assertEqual(check["counts"]["lintErrors"], 0)

    def test_golden_covers_requirements_structure_and_parameters(self):
        text = generate_sysml(golden_model())["text"]
        for needle in (
            "requirement def MissionEndurance",
            "requirement def CruiseEndurance",
            "requirement def RotorSpeedRatioBand",
            "part def BatteryPack",
            "part def PowerChain",
            "part def UpperRotor",
            "attribute enduranceHours : Real = 4.0;",
            "attribute batteryCapacityWh : Real = 1200.0;",
            "// quantity: 8",
        ):
            self.assertIn(needle, text, msg="标杆案例缺少：%s" % needle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
