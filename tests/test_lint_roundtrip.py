"""T5 —— 回验底座（``lint_sysml`` / ``extract_declarations`` / ``roundtrip_check``）。

lint 是 MVP 的「解析回验」替代形态（见 ``docs/T0-调研结论.md`` §2.4），
因此它的**错误定位能力**必须有测试兜住：这里逐条验证「能带行列位置地抓住什么」，
以及**诚实地验证它抓不到什么**（不夸大能力边界）。
"""

from __future__ import annotations

import unittest

from _support import (
    base_model,
    extended_model,
    extract_connections,
    extract_declarations,
    generate_sysml,
    golden_model,
    lint_sysml,
    roundtrip_check,
)


class TestLintAccepts(unittest.TestCase):
    def test_generated_text_is_clean(self):
        result = lint_sysml(generate_sysml(base_model())["text"])
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertEqual(result["stats"]["errors"], 0)

    def test_golden_text_is_clean(self):
        result = lint_sysml(generate_sysml(golden_model())["text"])
        self.assertTrue(result["ok"], msg=result["errors"])

    def test_generated_text_with_new_kinds_is_clean(self):
        result = lint_sysml(generate_sysml(extended_model())["text"])
        self.assertTrue(result["ok"], msg=result["errors"])

    def test_hand_written_new_syntax_is_clean(self):
        """单位后缀 / 多重度 / initial / transition / connect + 结构化注释都要被接受。"""
        text = (
            "package A {\n"
            "    part def B;\n"
            "    part b : B[8];\n"
            "    attribute v : Real = 1.0 [V];\n"
            "    state def M {\n"
            "        entry; then Idle;\n"
            "        state Idle;\n"
            "        state Running;\n"
            "        // trigger: start\n"
            "        transition T_Idle_to_Running_0 first Idle if (v > 0) then Running;\n"
            "    }\n"
            "    // Connection C1 flowKind=electrical\n"
            "    connect b to b;\n"
            "}\n"
        )
        result = lint_sysml(text)
        self.assertTrue(result["ok"], msg=result["errors"])

    def test_standard_library_imports_are_clean(self):
        """生成器固定输出的两行标准库 import 必须被 lint 认作合法语句。"""
        text = (
            "package A {\n"
            "    private import ScalarValues::*;\n"
            "    private import SI::*;\n"
            "    part def B;\n"
            "}\n"
        )
        result = lint_sysml(text)
        self.assertTrue(result["ok"], msg=result["errors"])

    def test_unknown_import_prefix_is_clean_statement(self):
        """lint 只做语句形态自查：public import 也是合法语句（语义另说）。"""
        text = "package A {\n    public import SI::*;\n}\n"
        self.assertTrue(lint_sysml(text)["ok"])

    def test_hand_written_minimal_text_is_clean(self):
        text = "package A {\n    part def B;\n    part c : B;\n}\n"
        self.assertTrue(lint_sysml(text)["ok"])

    def test_doc_comment_statement_needs_no_semicolon(self):
        text = "package A {\n    requirement def R {\n        doc /* 说明 */\n    }\n}\n"
        result = lint_sysml(text)
        self.assertTrue(result["ok"], msg=result["errors"])


class TestLintRejects(unittest.TestCase):
    def assertReports(self, text: str, code: str, *, line: int = None):
        result = lint_sysml(text)
        self.assertFalse(result["ok"], msg="本该报错：%r" % text)
        found = [e for e in result["errors"] if e["code"] == code]
        self.assertTrue(found, msg="期望 %s，实际 %s" % (code, [e["code"] for e in result["errors"]]))
        if line is not None:
            self.assertEqual(found[0]["line"], line)
        # 每条错误都必须带行列与出错行原文
        for entry in result["errors"]:
            self.assertGreaterEqual(entry["line"], 1)
            self.assertGreaterEqual(entry["column"], 1)
            self.assertIsInstance(entry["lineText"], str)
        return found[0]

    def test_unclosed_brace_is_located(self):
        entry = self.assertReports("package A {\n    part def B {\n", "L001", line=1)
        self.assertIn("{", entry["message"])

    def test_stray_closing_brace_is_located(self):
        self.assertReports("package A {\n}\n}\n", "L005", line=3)

    def test_unclosed_block_comment(self):
        self.assertReports("package A {\n    /* 没关掉\n}\n", "L002", line=2)

    def test_unclosed_string_literal(self):
        self.assertReports('package A {\n    attribute x : String = "abc;\n}\n', "L003", line=2)

    def test_unknown_statement_keyword(self):
        self.assertReports("package A {\n    frobnicate x;\n}\n", "L004", line=2)

    def test_statement_missing_terminator(self):
        self.assertReports("package A {\n    part def B\n}\n", "L006", line=2)

    def test_missing_package_wrapper_warns(self):
        result = lint_sysml("part def A;\n")
        self.assertIn("L007", [w["code"] for w in result["warnings"]])

    def test_connection_annotation_missing_flow_kind(self):
        self.assertReports(
            "package A {\n"
            "    // Connection C1\n"
            "    connect b to c;\n"
            "}\n",
            "L008",
            line=2,
        )

    def test_connection_annotation_without_connect_statement(self):
        self.assertReports(
            "package A {\n"
            "    // Connection C1 flowKind=electrical\n"
            "}\n",
            "L009",
            line=2,
        )

    def test_transition_must_use_official_form(self):
        """`transition from A to B ...` 不是官方记法，lint 必须报 L010。"""
        self.assertReports(
            "package A {\n"
            "    state def S {\n"
            "        state A;\n"
            "        state B;\n"
            "        transition from A to B when start;\n"
            "    }\n"
            "}\n",
            "L010",
            line=5,
        )

    def test_non_string_input_is_rejected(self):
        self.assertFalse(lint_sysml(None)["ok"])

    def test_line_numbers_point_at_the_right_line(self):
        text = "package A {\n    part def B;\n    attribute x : Real\n}\n"
        entry = self.assertReports(text, "L006")
        self.assertEqual(entry["line"], 3)
        self.assertIn("attribute x", entry["lineText"])
        self.assertEqual(entry["column"], 5)


class TestExtractDeclarations(unittest.TestCase):
    def test_extracts_all_kinds_from_base_model(self):
        result = extract_declarations(generate_sysml(base_model())["text"])
        self.assertEqual(result["byKind"].get("Package"), 1)
        self.assertEqual(result["byKind"].get("PartDefinition"), 1)
        self.assertEqual(result["byKind"].get("PartUsage"), 1)
        self.assertEqual(result["byKind"].get("Requirement"), 1)
        self.assertEqual(result["byKind"].get("ActionDefinition"), 1)
        self.assertEqual(result["byKind"].get("StateDefinition"), 1)
        self.assertEqual(result["byKind"].get("State"), 2)

    def test_ignores_declarations_inside_comments(self):
        text = (
            "package A {\n"
            "    // part def Ghost;\n"
            "    /* part def Phantom; */\n"
            "    part def Real1;\n"
            "}\n"
        )
        names = {d["name"] for d in extract_declarations(text)["declarations"]}
        self.assertIn("Real1", names)
        self.assertNotIn("Ghost", names)
        self.assertNotIn("Phantom", names)

    def test_ignores_declarations_inside_string_literals(self):
        text = (
            "package A {\n"
            '    attribute note : String = "part def Fake;";\n'
            "    part def Real1;\n"
            "}\n"
        )
        names = {d["name"] for d in extract_declarations(text)["declarations"]}
        self.assertNotIn("Fake", names)
        self.assertIn("Real1", names)

    def test_state_def_is_not_counted_as_state(self):
        text = "package A {\n    state def M {\n        state Idle;\n    }\n}\n"
        result = extract_declarations(text)
        self.assertEqual(result["byKind"].get("StateDefinition"), 1)
        self.assertEqual(result["byKind"].get("State"), 1)

    def test_records_part_usage_type_ref(self):
        result = extract_declarations(generate_sysml(base_model())["text"])
        usage = [d for d in result["declarations"] if d["kind"] == "PartUsage"][0]
        self.assertEqual(usage["typeRef"], "Motor")
        self.assertEqual(usage["scope"], "Demo")
        self.assertEqual(usage["scopeKind"], "Package")

    def test_records_scope_for_nested_declarations(self):
        model = base_model()
        for item in model["elements"]:
            if item["id"] == "PART-USE-MOTOR":
                item["owner"] = "PART-DEF-MOTOR"
        result = extract_declarations(generate_sysml(model)["text"])
        usage = [d for d in result["declarations"] if d["kind"] == "PartUsage"][0]
        self.assertEqual(usage["scope"], "Motor")
        self.assertEqual(usage["scopeKind"], "PartDefinition")

    def test_extracts_unit_and_multiplicity_suffixes(self):
        result = extract_declarations(generate_sysml(base_model())["text"])
        attribute = [
            d
            for d in result["declarations"]
            if d["kind"] == "Attribute" and d["name"] == "ratedVoltage"
        ][0]
        usage = [d for d in result["declarations"] if d["kind"] == "PartUsage"][0]
        self.assertEqual(attribute["unit"], "V")
        self.assertEqual(usage["multiplicity"], "4")

    def test_extracts_constraint_structured_comments(self):
        result = extract_declarations(generate_sysml(extended_model())["text"])
        constraint = [d for d in result["declarations"] if d["kind"] == "Constraint"][0]
        self.assertEqual(constraint["name"], "EnduranceBudget")
        self.assertEqual(constraint["expression"], "T = ratedVoltage / 2.0")
        self.assertEqual(constraint["parameters"], ["ratedVoltage"])
        self.assertEqual(constraint["scopeKind"], "Package")

    def test_extracts_connection_annotation_pair(self):
        result = extract_connections(generate_sysml(extended_model())["text"])
        self.assertTrue(result["ok"], msg=result)
        self.assertEqual(result["count"], 1)
        entry = result["connections"][0]
        self.assertEqual(entry["id"], "CONN-MOTOR-ESC")
        self.assertEqual(entry["flowKind"], "electrical")
        self.assertEqual(entry["name"], "motorToEsc")
        self.assertEqual(entry["source"], "motorOne")
        self.assertEqual(entry["target"], "escUnit")
        self.assertEqual(entry["description"], "电机由电调驱动。")

    def test_extracts_state_initial_and_transitions(self):
        model = base_model()
        for item in model["elements"]:
            if item["id"] == "STATE-A":
                item["properties"]["transitions"] = [
                    {"from": "Idle", "to": "Running", "trigger": "start command", "guard": "rpm > 1000"},
                    {"from": "Running", "to": "Idle"},
                ]
        result = extract_declarations(generate_sysml(model)["text"])
        state = [d for d in result["declarations"] if d["kind"] == "StateDefinition"][0]
        self.assertEqual(state["initial"], "Idle")
        self.assertEqual(
            state["transitions"],
            [
                {
                    "name": "Transition_Idle_to_Running_0",
                    "from": "Idle",
                    "to": "Running",
                    "guard": "rpm > 1000",
                    "trigger": "start command",
                },
                {
                    "name": "Transition_Running_to_Idle_1",
                    "from": "Running",
                    "to": "Idle",
                    "guard": None,
                    "trigger": None,
                },
            ],
        )


class TestRoundtrip(unittest.TestCase):
    def test_golden_roundtrip_is_exact(self):
        model = golden_model()
        text = generate_sysml(model)["text"]
        result = roundtrip_check(model, text)
        self.assertTrue(result["ok"], msg=result)
        # 元素数动态取自 golden IR，避免并行任务增删元素时这里再漂移
        expected = len(model["elements"])
        self.assertEqual(result["counts"]["irElements"], expected)
        self.assertEqual(result["counts"]["matched"], expected)

    def test_extended_roundtrip_is_exact(self):
        model = extended_model()
        text = generate_sysml(model)["text"]
        result = roundtrip_check(model, text)
        self.assertTrue(result["ok"], msg=result)
        self.assertEqual(result["counts"]["mismatched"], 0)
        self.assertEqual(result["connectionsByKind"], 1)

    def test_detects_constraint_expression_mismatch(self):
        model = extended_model()
        text = generate_sysml(model)["text"]
        damaged = text.replace("// expression: T = ratedVoltage / 2.0", "// expression: T = 0")
        result = roundtrip_check(model, damaged)
        self.assertFalse(result["ok"])
        self.assertIn("expression", [m["field"] for m in result["mismatched"]])

    def test_detects_constraint_parameters_mismatch(self):
        model = extended_model()
        text = generate_sysml(model)["text"]
        damaged = text.replace("// parameters: ratedVoltage", "// parameters: otherAttribute")
        result = roundtrip_check(model, damaged)
        self.assertFalse(result["ok"])
        self.assertIn("parameters", [m["field"] for m in result["mismatched"]])

    def test_detects_connection_flow_kind_mismatch(self):
        model = extended_model()
        text = generate_sysml(model)["text"]
        damaged = text.replace("flowKind=electrical", "flowKind=thermal")
        result = roundtrip_check(model, damaged)
        self.assertFalse(result["ok"])
        self.assertIn("flowKind", [m["field"] for m in result["mismatched"]])

    def test_detects_connection_endpoint_swap(self):
        model = extended_model()
        text = generate_sysml(model)["text"]
        damaged = text.replace("connect motorOne to escUnit;", "connect escUnit to motorOne;")
        result = roundtrip_check(model, damaged)
        self.assertFalse(result["ok"])
        self.assertEqual(
            {m["field"] for m in result["mismatched"]}, {"sourceRef", "targetRef"}
        )

    def test_detects_state_transition_guard_mismatch(self):
        model = base_model()
        for item in model["elements"]:
            if item["id"] == "STATE-A":
                item["properties"]["transitions"][0]["guard"] = "rpm > 1000"
        text = generate_sysml(model)["text"]
        damaged = text.replace("if (rpm > 1000)", "if (rpm > 2000)")
        result = roundtrip_check(model, damaged)
        self.assertFalse(result["ok"])
        self.assertIn("transitions", [m["field"] for m in result["mismatched"]])

    def test_detects_state_initial_mismatch(self):
        model = base_model()
        text = generate_sysml(model)["text"]
        damaged = text.replace("entry; then Idle;", "entry; then Running;")
        result = roundtrip_check(model, damaged)
        self.assertFalse(result["ok"])
        self.assertIn("initial", [m["field"] for m in result["mismatched"]])

    def test_detects_element_missing_from_text(self):
        """从文本里删掉一条声明，回验必须报 missing。"""
        model = base_model()
        text = generate_sysml(model)["text"]
        damaged = text.replace("    attribute ratedVoltage : Real = 24.0 [V];\n", "")
        result = roundtrip_check(model, damaged)
        self.assertFalse(result["ok"])
        self.assertEqual([m["name"] for m in result["missing"]], ["ratedVoltage"])

    def test_detects_extra_declaration_in_text(self):
        """文本里多出一条 IR 没有的声明，回验必须报 extra。"""
        model = base_model()
        text = generate_sysml(model)["text"]
        damaged = text.replace("package Demo {", "package Demo {\n    part def Stowaway;")
        result = roundtrip_check(model, damaged)
        self.assertFalse(result["ok"])
        self.assertIn("Stowaway", [e["name"] for e in result["extra"]])

    def test_detects_type_ref_mismatch(self):
        """文本里把 PartUsage 的类型改错，回验必须报 mismatched。"""
        model = base_model()
        text = generate_sysml(model)["text"]
        damaged = text.replace("part motorOne : Motor[4];", "part motorOne : WrongType[4];")
        result = roundtrip_check(model, damaged)
        self.assertFalse(result["ok"])
        self.assertEqual(result["mismatched"][0]["field"], "typeRef")
        self.assertEqual(result["mismatched"][0]["text"], "WrongType")

    def test_detects_lint_error_in_text(self):
        model = base_model()
        text = generate_sysml(model)["text"] + "}\n"
        result = roundtrip_check(model, text)
        self.assertFalse(result["ok"])
        self.assertGreater(result["counts"]["lintErrors"], 0)

    def test_requirement_threshold_attributes_are_not_extra(self):
        """渲染在 requirement def 体内的阈值 attribute 不是独立元素，不该被当成 extra。"""
        result = roundtrip_check(golden_model(), generate_sysml(golden_model())["text"])
        self.assertEqual(result["extra"], [])

    def test_handles_invalid_ir_json_string(self):
        result = roundtrip_check("{oops", "package A { }")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


class TestHonestLimits(unittest.TestCase):
    """诚实标注能力边界：这些**抓不到**，测试固化下来免得后人误以为能抓。"""

    def test_lint_does_not_check_sysml_semantics(self):
        """结构自洽但语义荒谬的文本会被放行——方案 10.1 已明确这是设计边界。"""
        text = (
            "package A {\n"
            "    part def B;\n"
            "    part b1 : TotallyUndefinedType;\n"  # 未定义的类型
            "}\n"
        )
        self.assertTrue(lint_sysml(text)["ok"])

    def test_roundtrip_does_not_check_type_existence(self):
        model = base_model()
        text = generate_sysml(model)["text"].replace(
            "part motorOne : Motor[4];", "part motorOne : Ghost[4];"
        )
        # 会报 mismatched（因为 IR 里是 Motor），但报的不是「Ghost 不存在」
        result = roundtrip_check(model, text)
        self.assertEqual(len(result["mismatched"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
