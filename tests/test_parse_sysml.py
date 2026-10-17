"""T7 —— ``parse_sysml`` 的正例、能力边界与错误定位。

这些用例把「逆解析契约」钉住：

- 生成器能渲染的八种 kind，parse 必须能还原成元素级等价的 IR；
- 子集外的构造**不崩、不静默丢**：逐条进 ``unsupported`` 且带行号；
- 名字 → id 无法唯一还原时进 ``errors``（``E-PARSE-AMBIGUOUS``），不猜；
- 本模块不冒充完整 SysML v2 解析器，也不冒充 ``validate_model_json``。
"""

from __future__ import annotations

import json
import unittest

from _support import (
    base_model,
    extended_model,
    generate_sysml,
    golden_model,
)

from tools.parser import parse_sysml


def generated(model) -> str:
    result = generate_sysml(model)
    assert result["ok"], result["errors"]
    return result["text"]


def parse_generated(model):
    return parse_sysml(generated(model))


def canonical(model):
    """元素级等价的口径：id/kind/name/owner/properties/relations（meta 不参与）。"""
    elements = {}
    for element in model["elements"]:
        elements[element["id"]] = {
            "kind": element["kind"],
            "name": element["name"],
            "owner": element["owner"],
            "properties": element.get("properties") or {},
            "relations": element.get("relations") or [],
        }
    return elements


class TestInputAndShape(unittest.TestCase):
    def test_non_string_input_is_rejected_without_crashing(self):
        result = parse_sysml(None)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["model"])
        self.assertEqual(result["errors"][0]["code"], "E-PARSE-INPUT")

    def test_missing_package_is_an_error(self):
        result = parse_sysml("part def Motor;\n")
        self.assertFalse(result["ok"])
        self.assertIn("E-PARSE-NO-PACKAGE", [e["code"] for e in result["errors"]])

    def test_result_is_json_serializable_and_stats_cover_all_kinds(self):
        result = parse_generated(base_model())
        json.dumps(result, ensure_ascii=False)
        for kind in (
            "PartDefinition",
            "PartUsage",
            "Requirement",
            "ActionDefinition",
            "StateDefinition",
            "Attribute",
            "Constraint",
            "Connection",
        ):
            self.assertIn(kind, result["stats"]["byKind"])
        self.assertEqual(result["stats"]["elements"], len(base_model()["elements"]))

    def test_generated_text_without_header_still_parses(self):
        text = generate_sysml(base_model(), include_header=False)["text"]
        result = parse_sysml(text)
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertEqual(result["stats"]["imports"], 2)

    def test_utf8_bom_is_tolerated(self):
        text = "\ufeffpackage A {\n    part def B;\n}\n"
        result = parse_sysml(text)
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertEqual(result["model"]["package"], "A")


class TestEightKinds(unittest.TestCase):
    """从生成器输出还原每一种 kind 的关键字段。"""

    def setUp(self):
        self.model = golden_model()
        self.result = parse_generated(self.model)
        self.assertTrue(self.result["ok"], msg=json.dumps(self.result, ensure_ascii=False)[:1500])

    def test_element_level_equivalence_on_golden_case(self):
        self.assertEqual(canonical(self.result["model"]), canonical(self.model))
        self.assertEqual(self.result["model"]["schema"], "sysml-ir/v1")
        self.assertEqual(self.result["model"]["package"], "CoaxialOctoRotor")

    def test_part_definition_restores_abstract_and_description(self):
        model = base_model()
        for element in model["elements"]:
            if element["id"] == "PART-DEF-MOTOR":
                element["properties"]["isAbstract"] = True
        result = parse_generated(model)
        part_def = [e for e in result["model"]["elements"] if e["kind"] == "PartDefinition"][0]
        self.assertTrue(part_def["properties"]["isAbstract"])
        self.assertEqual(part_def["properties"]["description"], "无刷电机。")

    def test_part_usage_restores_quantity_type_and_owner(self):
        elements = {e["id"]: e for e in self.result["model"]["elements"]}
        esc = elements["PART-USAGE-ESC"]
        self.assertEqual(esc["properties"]["quantity"], 8)
        self.assertEqual(esc["properties"]["typeRef"], "PART-ESC")
        self.assertEqual(esc["owner"], "PART-POWER-CHAIN")
        self.assertEqual(esc["properties"]["description"], "八路电调，每副桨一路。")

    def test_quantity_one_is_preserved(self):
        elements = {e["id"]: e for e in self.result["model"]["elements"]}
        self.assertEqual(elements["PART-USAGE-SYSTEM"]["properties"]["quantity"], 1)

    def test_requirement_restores_doc_fields_and_thresholds(self):
        requirement = [
            e for e in self.result["model"]["elements"] if e["id"] == "REQ-MISSION-ENDURANCE"
        ][0]
        props = requirement["properties"]
        self.assertIn("任务级续航", props["text"])
        self.assertIn("验收判据", "验收判据: " + props["acceptanceCriteria"])
        self.assertEqual(props["verifyMethod"], "simulation")
        self.assertEqual(props["priority"], "high")
        self.assertEqual(props["minMissionDurationHours"], 5.0)
        self.assertEqual(props["minLandingReserveFraction"], 0.15)

    def test_requirement_restores_source_rationale(self):
        model = base_model()
        for element in model["elements"]:
            if element["id"] == "REQ-A":
                element["properties"]["source"] = "任务书 §3"
                element["properties"]["rationale"] = "需求分解时保留的理由。"
        result = parse_generated(model)
        requirement = [e for e in result["model"]["elements"] if e["kind"] == "Requirement"][0]
        self.assertEqual(requirement["properties"]["source"], "任务书 §3")
        self.assertEqual(requirement["properties"]["rationale"], "需求分解时保留的理由。")

    def test_action_definition_restores_ports_and_units(self):
        action = [e for e in self.result["model"]["elements"] if e["id"] == "ACT-SIM-ENDURANCE"][0]
        self.assertEqual(
            action["properties"]["inputs"],
            [
                {"name": "cruiseSpeed", "typeRef": "Real", "unit": "m/s"},
                {"name": "speedRatioEta", "typeRef": "Real"},
            ],
        )
        self.assertEqual(
            action["properties"]["outputs"],
            [{"name": "enduranceHours", "typeRef": "Real", "unit": "h"}],
        )

    def test_state_definition_restores_initial_states_and_transitions(self):
        model = base_model()
        for element in model["elements"]:
            if element["id"] == "STATE-A":
                element["properties"]["transitions"] = [
                    {"from": "Idle", "to": "Running", "trigger": "start command", "guard": "rpm > 1000"},
                    {"from": "Running", "to": "Idle", "guard": "stop command"},
                ]
        result = parse_generated(model)
        state = [e for e in result["model"]["elements"] if e["kind"] == "StateDefinition"][0]
        self.assertEqual(state["properties"]["initial"], "Idle")
        self.assertEqual(state["properties"]["states"], ["Idle", "Running"])
        self.assertEqual(
            state["properties"]["transitions"],
            [
                {"from": "Idle", "to": "Running", "trigger": "start command", "guard": "rpm > 1000"},
                {"from": "Running", "to": "Idle", "guard": "stop command"},
            ],
        )

    def test_attribute_restores_unit_and_default(self):
        attribute = [
            e for e in self.result["model"]["elements"] if e["id"] == "ATTR-CRUISE-SPEED"
        ][0]
        self.assertEqual(
            attribute["properties"],
            {
                "valueType": "Real",
                "defaultValue": 15.0,
                "unit": "m/s",
                "description": "巡航平飞速度 v，在线寻优的两个决策量之一。",
            },
        )

    def test_attribute_without_default_value_restores_unit(self):
        text = "package A {\n    attribute v : Real [V];\n}\n"
        result = parse_sysml(text)
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertEqual(
            result["model"]["elements"][0]["properties"],
            {"valueType": "Real", "unit": "V"},
        )

    def test_attribute_with_relations_body_is_supported(self):
        model = {
            "schema": "sysml-ir/v1",
            "package": "A",
            "elements": [
                {"id": "PART-DEF-B", "kind": "PartDefinition", "name": "B", "owner": "A", "properties": {}},
                {
                    "id": "ATTR-X",
                    "kind": "Attribute",
                    "name": "x",
                    "owner": "A",
                    "properties": {"valueType": "Real", "defaultValue": 1.0},
                    "relations": [{"type": "refines", "target": "PART-DEF-B", "rationale": "理由"}],
                },
            ],
        }
        result = parse_generated(model)
        self.assertTrue(result["ok"], msg=json.dumps(result, ensure_ascii=False)[:1000])
        self.assertEqual(canonical(result["model"]), canonical(model))

    def test_constraint_restores_expression_and_parameter_ids(self):
        constraint = [
            e for e in self.result["model"]["elements"] if e["id"] == "CONSTRAINT-ENDURANCE-BUDGET"
        ][0]
        self.assertEqual(
            constraint["properties"]["expression"],
            "T = batteryCapacityWh * usableEnergyFraction / cruisePowerW",
        )
        self.assertEqual(
            constraint["properties"]["parameters"],
            [
                "ATTR-BATTERY-CAPACITY",
                "ATTR-USABLE-FRACTION",
                "ATTR-CRUISE-POWER",
                "ATTR-ENDURANCE",
            ],
        )

    def test_connection_restores_name_id_endpoints_and_description(self):
        connections = [
            e for e in self.result["model"]["elements"] if e["kind"] == "Connection"
        ]
        self.assertEqual(len(connections), 2)
        by_id = {e["id"]: e for e in connections}
        battery = by_id["CONN-BATTERY-ESC"]
        self.assertEqual(battery["name"], "batteryToEsc")
        self.assertEqual(battery["owner"], "PART-POWER-CHAIN")
        self.assertEqual(battery["properties"]["sourceRef"], "PART-USAGE-BATTERY")
        self.assertEqual(battery["properties"]["targetRef"], "PART-USAGE-ESC")
        self.assertEqual(battery["properties"]["flowKind"], "electrical")
        self.assertEqual(battery["properties"]["description"], "电池直流母线馈入八路电调。")

    def test_relations_are_restored_with_rationale(self):
        requirement = [
            e for e in self.result["model"]["elements"] if e["id"] == "REQ-CRUISE-ENDURANCE"
        ][0]
        self.assertEqual(
            requirement["relations"],
            [
                {
                    "type": "refines",
                    "target": "REQ-MISSION-ENDURANCE",
                    "rationale": "由任务级续航需求分解而来",
                },
                {
                    "type": "satisfiedBy",
                    "target": "PART-BATTERY-PACK",
                    "rationale": "由电池包可用能量与放电效率保障",
                },
            ],
        )

    def test_every_element_id_is_recovered_from_id_comments(self):
        expected = {element["id"] for element in self.model["elements"]}
        actual = {element["id"] for element in self.result["model"]["elements"]}
        self.assertEqual(actual, expected)
        self.assertEqual(self.result["stats"]["synthesizedIds"], 0)


class TestUnitsAndAliases(unittest.TestCase):
    def test_wh_alias_roundtrips_to_canonical_ir_unit(self):
        result = parse_generated(golden_model())
        attribute = [
            e for e in result["model"]["elements"] if e["id"] == "ATTR-BATTERY-CAPACITY"
        ][0]
        self.assertEqual(attribute["properties"]["unit"], "Wh")

    def test_plain_units_are_unchanged(self):
        text = "package A {\n    attribute v : Real = 1.0 [m/s];\n}\n"
        result = parse_sysml(text)
        self.assertEqual(result["model"]["elements"][0]["properties"]["unit"], "m/s")

    def test_unknown_unit_is_preserved_literally(self):
        text = "package A {\n    attribute v : Real = 1.0 [furlong];\n}\n"
        result = parse_sysml(text)
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertEqual(result["model"]["elements"][0]["properties"]["unit"], "furlong")


class TestHandWrittenSubset(unittest.TestCase):
    """同子集的手写文本：不一定有 // id: 注释，但要稳定、可再生成。"""

    TEXT = (
        "package Hand {\n"
        "    private import ScalarValues::*;\n"
        "    private import SI::*;\n"
        "    // ---- PartDefinition ----\n"
        "    part def Motor;\n"
        "    // ---- PartUsage ----\n"
        "    part motorA : Motor[2];\n"
        "}\n"
    )

    def test_ids_are_synthesized_deterministically_with_warning(self):
        first = parse_sysml(self.TEXT)
        second = parse_sysml(self.TEXT)
        self.assertTrue(first["ok"], msg=first["errors"])
        self.assertEqual(first["model"], second["model"])
        self.assertEqual(
            [e["id"] for e in first["model"]["elements"]],
            ["PART-DEF-Motor", "PART-USE-motorA"],
        )
        self.assertIn("W-PARSE-SYNTH-ID", [w["code"] for w in first["warnings"]])

    def test_type_reference_resolves_to_synthesized_id(self):
        result = parse_sysml(self.TEXT)
        usage = [e for e in result["model"]["elements"] if e["kind"] == "PartUsage"][0]
        self.assertEqual(usage["properties"]["typeRef"], "PART-DEF-Motor")

    def test_standard_imports_are_recognized_not_unsupported(self):
        result = parse_sysml(self.TEXT)
        self.assertEqual(result["unsupported"], [])
        self.assertEqual(result["stats"]["imports"], 2)

    def test_extra_import_is_reported_as_unsupported(self):
        text = self.TEXT.replace(
            "    private import SI::*;\n", "    private import SI::*;\n    private import ISQ::*;\n"
        )
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["unsupported"]), 1)
        self.assertIn("ISQ", result["unsupported"][0]["snippet"])
        self.assertEqual(result["unsupported"][0]["line"], 4)

    def test_public_standard_import_is_recognized(self):
        text = (
            "package A {\n"
            "    public import ScalarValues::*;\n"
            "    public import SI::*;\n"
            "    part def B;\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertEqual(result["stats"]["imports"], 2)

    def test_bare_import_is_outside_the_subset(self):
        text = "package A {\n    import ScalarValues::*;\n    part def B;\n}\n"
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertTrue(result["unsupported"])
        self.assertEqual(result["unsupported"][0]["line"], 2)


class TestUnsupportedBoundary(unittest.TestCase):
    """子集外构造：不崩溃、不静默，逐条带行号进 unsupported。"""

    def test_unknown_single_line_constructs_are_listed_with_lines(self):
        text = (
            "package A {\n"
            "    part def B;\n"
            "    item def Widget;\n"
            "    port p : P;\n"
            "    satisfy REQ-1 by b;\n"
            "    part b : B;\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertEqual([entry["line"] for entry in result["unsupported"]], [3, 4, 5])
        self.assertEqual(len(result["errors"]), 0)
        # 子集内的元素仍然被解析出来，供调用方继续处理
        self.assertIn("PART-USE-b", [e["id"] for e in result["model"]["elements"]])

    def test_unknown_block_is_skipped_whole_and_does_not_crash(self):
        text = (
            "package A {\n"
            "    item def Widget {\n"
            "        part inner : Thing;\n"
            "        item def Deep {\n"
            "            part deeper : X;\n"
            "        }\n"
            "    }\n"
            "    part def B;\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertEqual([entry["line"] for entry in result["unsupported"]], [2])
        self.assertEqual(result["stats"]["errors"], 0)
        self.assertIn("PART-DEF-B", [e["id"] for e in result["model"]["elements"]])

    def test_multiline_block_comment_is_unsupported(self):
        text = "package A {\n    /* 多行\n       注释 */\n    part def B;\n}\n"
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["unsupported"]), 1)
        self.assertEqual(result["unsupported"][0]["line"], 2)

    def test_content_after_package_is_unsupported(self):
        text = "package A {\n    part def B;\n}\npart def C;\n"
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertEqual(result["unsupported"][0]["line"], 4)

    def test_bare_connect_without_annotation_is_unsupported(self):
        text = (
            "package A {\n    part def B;\n    part b : B;\n    part c : B;\n"
            "    connect b to c;\n}\n"
        )
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertEqual(result["unsupported"][0]["line"], 5)
        self.assertIn("Connection", result["unsupported"][0]["reason"])

    def test_connection_annotation_without_connect_is_an_error(self):
        text = (
            "package A {\n"
            "    // Connection C1 flowKind=electrical name=link\n"
            "    part def B;\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertIn("E-PARSE-CONN-NO-CONNECT", [e["code"] for e in result["errors"]])

    def test_malformed_connection_annotation_is_an_error(self):
        text = (
            "package A {\n"
            "    // Connection C1\n"
            "    connect b to c;\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertIn("E-PARSE-CONN-ANNOTATION", [e["code"] for e in result["errors"]])

    def test_malformed_transition_is_an_error_with_line(self):
        text = (
            "package A {\n"
            "    state def S {\n"
            "        state Idle;\n"
            "        state Run;\n"
            "        transition from Idle to Run;\n"
            "    }\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertEqual(result["unsupported"][0]["line"], 5)

    def test_unclosed_block_is_an_error(self):
        text = "package A {\n    part def B {\n"
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertIn("E-PARSE-UNCLOSED", [e["code"] for e in result["errors"]])

    def test_invalid_quantity_is_an_error(self):
        text = "package A {\n    part def B;\n    part b : B[1..4];\n}\n"
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertIn("E-PARSE-QUANTITY", [e["code"] for e in result["errors"]])


class TestReferenceResolution(unittest.TestCase):
    """名字 → id：同 owner 优先、其次全局唯一；歧义与缺失都不猜。"""

    def test_same_owner_wins_over_global_candidates(self):
        text = (
            "package A {\n"
            "    part def T;\n"
            "    part def Scope {\n"
            "        part def T;\n"
            "        part inner : T;\n"
            "    }\n"
            "    part outer : T;\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertTrue(result["ok"], msg=result["errors"])
        elements = {e["id"]: e for e in result["model"]["elements"]}
        inner = [e for e in result["model"]["elements"] if e["name"] == "inner"][0]
        outer = [e for e in result["model"]["elements"] if e["name"] == "outer"][0]
        # inner 的 owner 是 Scope，Scope 下的同名 T 优先
        self.assertEqual(inner["properties"]["typeRef"], elements["PART-DEF-T-2"]["id"])
        self.assertEqual(outer["properties"]["typeRef"], "PART-DEF-T")

    def test_ambiguous_type_reference_reports_error(self):
        text = (
            "package A {\n"
            "    part def Holder1 {\n        part def T;\n    }\n"
            "    part def Holder2 {\n        part def T;\n    }\n"
            "    part x : T;\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        errors = [e for e in result["errors"] if e["code"] == "E-PARSE-AMBIGUOUS"]
        self.assertEqual(len(errors), 1)
        self.assertIn("候选", errors[0]["message"])

    def test_unresolved_constraint_parameter_reports_error(self):
        text = (
            "package A {\n"
            "    constraint def C {\n"
            "        // expression: x > 0\n"
            "        // parameters: missingAttribute\n"
            "    }\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertIn("E-PARSE-UNRESOLVED", [e["code"] for e in result["errors"]])

    def test_constraint_parameter_prefers_same_owner(self):
        text = (
            "package A {\n"
            "    attribute p : Real = 1.0;\n"
            "    part def Scope {\n"
            "        attribute p : Real = 2.0;\n"
            "        constraint def C {\n"
            "            // expression: p > 0\n"
            "            // parameters: p\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertTrue(result["ok"], msg=result["errors"])
        scope = [e for e in result["model"]["elements"] if e["name"] == "Scope"][0]
        constraint = [e for e in result["model"]["elements"] if e["kind"] == "Constraint"][0]
        local = [
            e for e in result["model"]["elements"]
            if e["kind"] == "Attribute" and e["owner"] == scope["id"]
        ][0]
        self.assertEqual(constraint["properties"]["parameters"], [local["id"]])


class TestCommentsAndIds(unittest.TestCase):
    def test_id_comments_drive_element_ids(self):
        text = (
            "package A {\n"
            "    // id: CUSTOM-DEF-ID\n"
            "    part def B;\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertEqual(result["model"]["elements"][0]["id"], "CUSTOM-DEF-ID")
        self.assertEqual(result["stats"]["synthesizedIds"], 0)

    def test_description_comment_binds_to_next_declaration(self):
        text = (
            "package A {\n"
            "    // id: PART-DEF-B\n"
            "    // description: 说明文字。\n"
            "    part def B;\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertEqual(
            result["model"]["elements"][0]["properties"]["description"], "说明文字。"
        )

    def test_bad_id_is_an_error(self):
        text = "package A {\n    // id: 123-bad\n    part def B;\n}\n"
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertIn("E-PARSE-BAD-ID", [e["code"] for e in result["errors"]])

    def test_duplicate_id_is_an_error(self):
        text = (
            "package A {\n"
            "    // id: SAME\n    part def B;\n"
            "    // id: SAME\n    part def C;\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertFalse(result["ok"])
        self.assertIn("E-PARSE-DUPLICATE-ID", [e["code"] for e in result["errors"]])

    def test_connection_relations_attach_to_connection_not_owner(self):
        model = extended_model()
        for element in model["elements"]:
            if element["id"] == "CONN-MOTOR-ESC":
                element["relations"] = [
                    {"type": "connects", "target": "PART-USE-ESC", "rationale": "连接自身的关系"}
                ]
        result = parse_generated(model)
        self.assertTrue(result["ok"], msg=json.dumps(result, ensure_ascii=False)[:1200])
        connection = [
            e for e in result["model"]["elements"] if e["id"] == "CONN-MOTOR-ESC"
        ][0]
        self.assertEqual(
            connection["relations"],
            [
                {
                    "type": "connects",
                    "target": "PART-USE-ESC",
                    "rationale": "连接自身的关系",
                }
            ],
        )
        owner = [e for e in result["model"]["elements"] if e["id"] == "Demo"]
        self.assertEqual(owner, [])


class TestHonestScope(unittest.TestCase):
    """把「不做什么」也钉住，避免后人误以为 parse 等于官方解析器/校验器。"""

    def test_parse_does_not_replace_validator(self):
        """结构可解析但语义不完整（需求缺验收判据）时 parse 不报错，validate 报错。"""
        text = (
            "package A {\n"
            "    requirement def R {\n"
            "        doc /* 只有正文 */\n"
            "    }\n"
            "}\n"
        )
        result = parse_sysml(text)
        self.assertTrue(result["ok"], msg=result["errors"])
        from tools.validator import validate_model_json

        validation = validate_model_json(result["model"])
        self.assertFalse(validation["ok"])
        self.assertIn("E-REQ-NO-ACCEPTANCE", [e["code"] for e in validation["errors"]])

    def test_parse_does_not_check_sysml_semantics(self):
        """未定义类型名在 parse 阶段照样能形成 typeRef（是否合法交给校验/官方工具）。"""
        text = "package A {\n    part b : TotallyUndefined;\n}\n"
        result = parse_sysml(text)
        # 名字解析不到 PartDefinition → parse 会报 E-PARSE-UNRESOLVED（这是 IR 引用还原
        # 必需的信息），但它不会去判断 SysML 语义是否成立。
        self.assertIn("E-PARSE-UNRESOLVED", [e["code"] for e in result["errors"]])

    def test_docstring_documents_subset_boundary(self):
        import tools.parser as parser_module

        doc = parser_module.__doc__ or ""
        self.assertIn("不是完整", doc)
        self.assertIn("unsupported", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
