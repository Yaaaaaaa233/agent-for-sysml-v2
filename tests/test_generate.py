"""T5 —— ``generate_sysml`` 的正例、确定性与拒绝行为。"""

from __future__ import annotations

import json
import unittest

from _support import (
    base_model,
    codes,
    edit_element,
    extended_model,
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
        self.assertIn("        part motorOne : Motor[4];", text)

    def test_renders_part_usage_with_resolved_type_name(self):
        """typeRef 渲染成被引用元素的 **name**（Motor），而不是内部 id（PART-DEF-MOTOR）。"""
        self.assertIn("part motorOne : Motor[4];", self.text)
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

    def test_renders_state_transitions_as_formal_syntax(self):
        """初始化与迁移用官方记法（trigger 作为结构化注释；见 schema/渲染约定.md）。"""
        self.assertIn("entry; then Idle;", self.text)
        self.assertIn("state Idle;", self.text)
        self.assertIn("state Running;", self.text)
        self.assertIn("// trigger: start command", self.text)
        self.assertIn(
            "transition Transition_Idle_to_Running_0 first Idle then Running;", self.text
        )
        self.assertNotIn("// transitions:", self.text)

    def test_renders_state_transition_guard_and_optional_trigger(self):
        """guard 渲染为官方 `if (...)`；没有 trigger 时不产生 trigger 注释。"""
        model = base_model()
        for item in model["elements"]:
            if item["id"] == "STATE-A":
                item["properties"]["transitions"] = [
                    {"from": "Idle", "to": "Running", "trigger": "start command", "guard": "rpm > 1000"},
                    {"from": "Running", "to": "Idle", "guard": "stop command"},
                ]
        text = generate_sysml(model)["text"]
        self.assertIn("// trigger: start command", text)
        self.assertIn(
            "transition Transition_Idle_to_Running_0 first Idle if (rpm > 1000) then Running;",
            text,
        )
        self.assertIn(
            "transition Transition_Running_to_Idle_1 first Running if (stop command) then Idle;",
            text,
        )
        self.assertEqual(text.count("// trigger:"), 1)

    def test_renders_attribute_with_unit_suffix(self):
        """单位改用正式后缀 `[V]`，不再以行内注释承载。"""
        line = [l for l in self.lines if "ratedVoltage" in l][0]
        self.assertEqual(line.strip(), "attribute ratedVoltage : Real = 24.0 [V];")
        self.assertNotIn("// unit:", line)

    def test_renders_attribute_without_unit_has_no_suffix(self):
        model = base_model()
        for item in model["elements"]:
            if item["id"] == "ATTR-A":
                item["properties"].pop("unit")
        text = generate_sysml(model)["text"]
        self.assertIn("attribute ratedVoltage : Real = 24.0;", text)

    def test_renders_quantity_suffix_including_one(self):
        """quantity 存在就渲染 `[n]`（含 n=1）；不存在则不渲染。"""
        model = base_model()
        for item in model["elements"]:
            if item["id"] == "PART-USE-MOTOR":
                item["properties"]["quantity"] = 1
        self.assertIn("part motorOne : Motor[1];", generate_sysml(model)["text"])

        for item in model["elements"]:
            if item["id"] == "PART-USE-MOTOR":
                item["properties"].pop("quantity")
        self.assertIn("part motorOne : Motor;", generate_sysml(model)["text"])

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


class TestNewKindRendering(unittest.TestCase):
    """v1 增补：Constraint 块 + Connection 行 + 结构化注释。"""

    def setUp(self):
        self.model = extended_model()
        self.result = generate_sysml(self.model)
        self.assertTrue(self.result["ok"], msg=codes(self.result))
        self.text = self.result["text"]

    def test_renders_constraint_def_with_structured_comments(self):
        self.assertIn("    constraint def EnduranceBudget {", self.text)
        self.assertIn("        // expression: T = ratedVoltage / 2.0", self.text)
        self.assertIn("        // parameters: ratedVoltage", self.text)
        self.assertTrue(self.text.rstrip().endswith("}"))

    def test_renders_connection_annotation_and_connect_statement(self):
        self.assertIn(
            "    // Connection CONN-MOTOR-ESC flowKind=electrical name=motorToEsc "
            "description: 电机由电调驱动。",
            self.text,
        )
        self.assertIn("    connect motorOne to escUnit;", self.text)

    def test_connection_without_description_omits_suffix(self):
        model = extended_model()
        for item in model["elements"]:
            if item["id"] == "CONN-MOTOR-ESC":
                item["properties"].pop("description")
        text = generate_sysml(model)["text"]
        self.assertIn("// Connection CONN-MOTOR-ESC flowKind=electrical name=motorToEsc", text)
        self.assertNotIn("flowKind=electrical name=motorToEsc description:", text)

    def test_constraint_parameters_render_names_not_ids(self):
        # id 现在只应出现在 `// id:` / 追溯注释里；参数行必须是 name
        parameter_lines = [
            line for line in self.text.split("\n") if "// parameters:" in line
        ]
        self.assertEqual(len(parameter_lines), 1)
        self.assertIn("ratedVoltage", parameter_lines[0])
        self.assertNotIn("ATTR-A", parameter_lines[0])

    def test_new_kinds_are_deterministic(self):
        first = generate_sysml(self.model)
        second = generate_sysml(self.model)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["text"], second["text"])

    def test_stats_count_new_kinds(self):
        stats = self.result["stats"]
        self.assertEqual(stats["byKind"]["Constraint"], 1)
        self.assertEqual(stats["byKind"]["Connection"], 1)

    def test_roundtrip_on_new_kinds_is_exact(self):
        check = roundtrip_check(self.model, self.text)
        self.assertTrue(check["ok"], msg=json.dumps(check, ensure_ascii=False)[:1200])
        self.assertEqual(check["counts"]["missing"], 0)
        self.assertEqual(check["counts"]["extra"], 0)
        self.assertEqual(check["counts"]["mismatched"], 0)


class TestRenderContractV2(unittest.TestCase):
    """v2 逆解析契约：标准库 import 头、逐元素 id 注释、单位别名。"""

    def test_emits_standard_library_imports_inside_package(self):
        text = generate_sysml(base_model())["text"]
        lines = text.split("\n")
        package_index = lines.index("package Demo {")
        self.assertEqual(lines[package_index + 1], "    private import ScalarValues::*;")
        self.assertEqual(lines[package_index + 2], "    private import SI::*;")
        self.assertIn("// ---- PartDefinition ----", text)

    def test_emits_id_comment_before_each_element(self):
        text = generate_sysml(base_model())["text"]
        for element in base_model()["elements"]:
            self.assertIn("// id: %s" % element["id"], text)
        # 声明前的顺序固定：id 在 description 之前
        self.assertIn(
            "    // id: PART-DEF-MOTOR\n    // description: 无刷电机。\n    part def Motor;",
            text,
        )

    def test_unit_alias_wh_is_rendered_as_product(self):
        text = generate_sysml(golden_model())["text"]
        self.assertIn("attribute batteryCapacityWh : Real = 1200.0 [W*h];", text)
        self.assertNotIn("[Wh]", text)

    def test_connection_name_is_encoded_in_annotation(self):
        text = generate_sysml(extended_model())["text"]
        self.assertIn("flowKind=electrical name=motorToEsc", text)

    def test_every_generated_kind_has_id_comment(self):
        model = extended_model()
        text = generate_sysml(model)["text"]
        for element in model["elements"]:
            if element["kind"] == "Connection":
                # Connection 没有具名声明，id 固定落在结构化注释里
                self.assertIn("// Connection %s " % element["id"], text)
            else:
                self.assertIn("// id: %s" % element["id"], text, msg=element["kind"])


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
            "attribute enduranceHours : Real = 4.0 [h];",
            "attribute batteryCapacityWh : Real = 1200.0 [W*h];",
            "part escUnit : ElectronicSpeedController[8]",
            "constraint def EnduranceBudget {",
            "// expression: T = batteryCapacityWh * usableEnergyFraction / cruisePowerW",
            "// Connection CONN-BATTERY-ESC flowKind=electrical",
            "connect batteryPack to escUnit;",
        ):
            self.assertIn(needle, text, msg="标杆案例缺少：%s" % needle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
