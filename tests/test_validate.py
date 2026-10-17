"""T5 —— ``validate_model_json`` 的正例与反例。

反例（必须被拒绝）覆盖任务书点名的六类错误：
缺 acceptanceCriteria / relations.target 悬空 / 同 owner 命名冲突 /
kind 枚举自创 / 数值字段写成字符串 / typeRef 悬空。
"""

from __future__ import annotations

import copy
import unittest

from _support import (
    base_model,
    codes,
    edit_element,
    element,
    extended_model,
    golden_model,
    mutate,
    validate_model_json,
)


class TestValidModels(unittest.TestCase):
    """正例：合法模型必须放行。"""

    def test_base_model_is_clean(self):
        """基准模型：ok 且**零 warning**（保证后面所有反例都是单一变量改动）。"""
        result = validate_model_json(base_model())
        self.assertTrue(result["ok"], msg=codes(result))
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])

    def test_golden_case_is_valid(self):
        """T4 标杆案例必须 ok=true、零 error。"""
        result = validate_model_json(golden_model())
        self.assertTrue(result["ok"], msg=codes(result))
        self.assertEqual(len(result["errors"]), 0)

    def test_accepts_json_string_input(self):
        """LLM 常直接吐字符串；工具应能吃 JSON 文本。"""
        import json

        result = validate_model_json(json.dumps(base_model(), ensure_ascii=False))
        self.assertTrue(result["ok"], msg=codes(result))

    def test_relations_are_optional(self):
        """relations 是可选字段（方案 4.2）。去掉后仍应合法。"""
        def drop(model):
            model.pop("relations", None)

        result = validate_model_json(edit_element(base_model(), "REQ-A", drop))
        self.assertTrue(result["ok"], msg=codes(result))

    def test_reports_schema_layer_status(self):
        """返回值要如实说明第二层（JSON Schema）跑没跑。"""
        result = validate_model_json(base_model())
        self.assertIn("schemaLayer", result)
        self.assertIn(
            result["schemaLayer"], {"unavailable", "skipped", "unreadable", "invalid"}
            | {"ok", }
            | {"ok(+%d)" % n for n in range(0, 50)},
        )


class TestRejectedModels(unittest.TestCase):
    """反例：每一类都必须被拒绝，并给出**具体错误码**。"""

    def assertRejected(self, model, expected_code: str):
        result = validate_model_json(model)
        self.assertFalse(result["ok"], msg="本该被拒绝却通过了：%s" % model)
        self.assertIn(expected_code, codes(result), msg="错误码不对：%s" % codes(result))
        return result

    # --- 1. 需求缺验收判据 ----------------------------------------------------------------
    def test_reject_requirement_without_acceptance_criteria(self):
        model = edit_element(base_model(), "REQ-A", lambda e: e["properties"].pop("acceptanceCriteria"))
        self.assertRejected(model, "E-REQ-NO-ACCEPTANCE")

    def test_reject_requirement_with_blank_acceptance_criteria(self):
        model = edit_element(
            base_model(), "REQ-A", lambda e: e["properties"].__setitem__("acceptanceCriteria", "   ")
        )
        self.assertRejected(model, "E-REQ-NO-ACCEPTANCE")

    def test_reject_requirement_without_text(self):
        model = edit_element(base_model(), "REQ-A", lambda e: e["properties"].pop("text"))
        self.assertRejected(model, "E-REQ-NO-TEXT")

    # --- 2. relations.target 悬空 ---------------------------------------------------------
    def test_reject_dangling_relation_target(self):
        model = edit_element(
            base_model(),
            "REQ-A",
            lambda e: e["relations"][0].__setitem__("target", "PART-DEF-DOES-NOT-EXIST"),
        )
        self.assertRejected(model, "E-REL-TARGET-DANGLING")

    def test_reject_relation_missing_rationale(self):
        model = edit_element(base_model(), "REQ-A", lambda e: e["relations"][0].pop("rationale"))
        self.assertRejected(model, "E-REL-FIELD-MISSING")

    def test_reject_blank_rationale(self):
        model = edit_element(base_model(), "REQ-A", lambda e: e["relations"][0].__setitem__("rationale", ""))
        self.assertRejected(model, "E-REL-NO-RATIONALE")

    # --- 3. 同 owner 命名冲突 -------------------------------------------------------------
    def test_reject_duplicate_name_same_owner(self):
        def rename(e):
            e["name"] = "Motor"  # 与 PART-DEF-MOTOR 同 owner（Demo）下重名

        self.assertRejected(edit_element(base_model(), "ATTR-A", rename), "E-NAME-DUP")

    def test_reject_duplicate_id(self):
        def clash(e):
            e["id"] = "REQ-A"

        self.assertRejected(edit_element(base_model(), "ACT-A", clash), "E-ID-DUP")

    # --- 4. kind 枚举自创 -----------------------------------------------------------------
    def test_reject_invented_kind(self):
        # 注：Constraint 自 v1 增补起已是合法 kind，因此自创值改用 BogusKind。
        model = edit_element(base_model(), "ACT-A", lambda e: e.__setitem__("kind", "BogusKind"))
        self.assertRejected(model, "E-KIND-INVALID")

    def test_reject_invented_relation_type(self):
        model = edit_element(
            base_model(), "REQ-A", lambda e: e["relations"][0].__setitem__("type", "derives")
        )
        self.assertRejected(model, "E-REL-TYPE-INVALID")

    def test_reject_invented_verify_method(self):
        model = edit_element(
            base_model(), "REQ-A", lambda e: e["properties"].__setitem__("verifyMethod", "vibes")
        )
        self.assertRejected(model, "E-ENUM-INVALID")

    def test_reject_invented_value_type(self):
        model = edit_element(
            base_model(), "ATTR-A", lambda e: e["properties"].__setitem__("valueType", "Float64")
        )
        self.assertRejected(model, "E-ENUM-INVALID")

    # --- 5. 数值字段写成字符串 -------------------------------------------------------------
    def test_reject_threshold_as_string_with_unit(self):
        """把「4 小时」整体塞进字符串——方案 4.4 第 5 条明令禁止。"""
        model = edit_element(
            base_model(),
            "REQ-A",
            lambda e: e["properties"].__setitem__("minEnduranceHours", "4 小时"),
        )
        self.assertRejected(model, "E-PROP-THRESHOLD-STRING")

    def test_reject_threshold_as_numeric_string(self):
        model = edit_element(
            base_model(), "REQ-A", lambda e: e["properties"].__setitem__("minEnduranceHours", "4.0")
        )
        self.assertRejected(model, "E-PROP-THRESHOLD-STRING")

    def test_reject_quantity_as_string(self):
        model = edit_element(
            base_model(), "PART-USE-MOTOR", lambda e: e["properties"].__setitem__("quantity", "4")
        )
        self.assertRejected(model, "E-PROP-TYPE")

    def test_reject_attribute_default_type_mismatch(self):
        model = edit_element(
            base_model(), "ATTR-A", lambda e: e["properties"].__setitem__("defaultValue", "twenty four")
        )
        self.assertRejected(model, "E-ATTR-DEFAULT-TYPE")

    # --- 6. typeRef 悬空 ------------------------------------------------------------------
    def test_reject_dangling_type_ref(self):
        model = edit_element(
            base_model(), "PART-USE-MOTOR", lambda e: e["properties"].__setitem__("typeRef", "PART-DEF-NOPE")
        )
        self.assertRejected(model, "E-PARTUSAGE-TYPEREF-DANGLING")

    def test_reject_type_ref_pointing_to_wrong_kind(self):
        """typeRef 必须指向 PartDefinition；指向 Requirement 应被拒。"""
        model = edit_element(
            base_model(), "PART-USE-MOTOR", lambda e: e["properties"].__setitem__("typeRef", "REQ-A")
        )
        self.assertRejected(model, "E-PARTUSAGE-TYPEREF-WRONGKIND")

    def test_reject_part_usage_without_type_ref(self):
        model = edit_element(base_model(), "PART-USE-MOTOR", lambda e: e["properties"].pop("typeRef"))
        self.assertRejected(model, "E-PROP-REQUIRED")

    # --- 其他结构错误 ---------------------------------------------------------------------
    def test_reject_missing_owner_target(self):
        model = edit_element(base_model(), "ATTR-A", lambda e: e.__setitem__("owner", "NoSuchOwner"))
        self.assertRejected(model, "E-OWNER-MISSING")

    def test_reject_missing_required_skeleton_field(self):
        model = edit_element(base_model(), "ATTR-A", lambda e: e.pop("owner"))
        self.assertRejected(model, "E-FIELD-MISSING")

    def test_reject_wrong_schema_version(self):
        self.assertRejected(mutate(base_model(), schema="sysml-ir/v2"), "E-SCHEMA-VERSION")

    def test_reject_root_not_object(self):
        result = validate_model_json(["not", "a", "model"])
        self.assertFalse(result["ok"])
        self.assertIn("E-ROOT-NOT-OBJECT", codes(result))

    def test_reject_invalid_json_string(self):
        result = validate_model_json("{ this is not json")
        self.assertFalse(result["ok"])
        self.assertIn("E-INPUT-NOT-JSON", codes(result))

    def test_reject_empty_elements(self):
        self.assertRejected(mutate(base_model(), elements=[]), "E-ELEMENTS-EMPTY")

    def test_reject_unknown_property_for_kind(self):
        """kind 与 properties 子结构必须匹配。"""
        model = edit_element(
            base_model(), "PART-DEF-MOTOR", lambda e: e["properties"].__setitem__("acceptanceCriteria", "x")
        )
        self.assertRejected(model, "E-PROP-UNKNOWN")

    def test_reject_state_transition_to_undeclared_state(self):
        def break_transition(e):
            e["properties"]["transitions"][0]["to"] = "Flying"

        self.assertRejected(edit_element(base_model(), "STATE-A", break_transition), "E-STATE-TRANSITION-ENDPOINT")

    def test_reject_name_that_is_not_an_identifier(self):
        model = edit_element(base_model(), "ATTR-A", lambda e: e.__setitem__("name", "rated voltage"))
        self.assertRejected(model, "E-NAME-INVALID")

    def test_kebab_case_id_is_allowed(self):
        """id 允许连字符（方案 2.3 的 REQ-CRUISE-ENDURANCE 形态），name 不允许。"""
        result = validate_model_json(golden_model())
        self.assertTrue(result["ok"], msg=codes(result))
        self.assertTrue(any(e["id"].startswith("REQ-") for e in golden_model()["elements"]))


class TestWarnings(unittest.TestCase):
    """warning 不是 error：不该拦住合法模型，但要说清风险。"""

    def test_warn_requirement_with_verify_method_but_no_verifies(self):
        def drop_verifier(model):
            model["relations"] = []

        model = edit_element(base_model(), "ACT-A", drop_verifier)
        result = validate_model_json(model)
        self.assertTrue(result["ok"], msg=codes(result))
        self.assertIn("W-REQ-NO-VERIFY", codes(result, "warnings"))

    def test_warn_requirement_without_satisfied_by(self):
        model = edit_element(base_model(), "REQ-A", lambda e: e.__setitem__("relations", []))
        result = validate_model_json(model)
        self.assertTrue(result["ok"], msg=codes(result))
        self.assertIn("W-REQ-NO-SATISFY", codes(result, "warnings"))

    def test_warn_unused_part_definition(self):
        """没有任何 PartUsage 使用某个 PartDefinition 时，应提示该定义没被实例化。"""
        result = validate_model_json(
            {
                "schema": "sysml-ir/v1",
                "package": "Demo",
                "elements": [
                    {
                        "id": "PART-DEF-ORPHAN",
                        "kind": "PartDefinition",
                        "name": "OrphanPart",
                        "owner": "Demo",
                        "properties": {},
                    }
                ],
            }
        )
        self.assertTrue(result["ok"], msg=codes(result))
        self.assertIn("W-PARTDEF-UNUSED", codes(result, "warnings"))
        self.assertIn("W-ELEMENT-ORPHAN", codes(result, "warnings"))

    def test_value_unit_object_form_is_accepted_with_warning(self):
        """{value, unit} 对象形态是合法写法（比纯数字更明确），给 warning 提示渲染口径。"""
        model = edit_element(
            base_model(),
            "REQ-A",
            lambda e: e["properties"].__setitem__("minEnduranceHours", {"value": 4.0, "unit": "h"}),
        )
        result = validate_model_json(model)
        self.assertTrue(result["ok"], msg=codes(result))
        self.assertIn("W-PROP-UNIT-OBJECT", codes(result, "warnings"))


class TestNewKindsValidation(unittest.TestCase):
    """v1 增补的 Constraint / Connection：正例 + 每条语义规则的反例。"""

    def assertRejected(self, model, expected_code: str):
        result = validate_model_json(model)
        self.assertFalse(result["ok"], msg="本该被拒绝却通过了：%s" % model)
        self.assertIn(expected_code, codes(result), msg="错误码不对：%s" % codes(result))
        return result

    def test_extended_model_is_clean_and_zero_warning(self):
        """新 kind 的基准模型：ok 且零 warning（证明没触发 W-ELEMENT-ORPHAN 等旧规则）。"""
        result = validate_model_json(extended_model())
        self.assertTrue(result["ok"], msg=codes(result))
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])

    def test_json_schema_layer_accepts_new_kinds(self):
        """JSON Schema（第二层）与新 kind 的 properties 定义必须一致。"""
        result = validate_model_json(extended_model(), use_json_schema=True)
        self.assertTrue(result["ok"], msg=codes(result))
        self.assertNotIn("E-SCHEMA", codes(result))

    # --- Constraint -------------------------------------------------------------------
    def test_reject_constraint_without_expression(self):
        model = edit_element(
            extended_model(),
            "CONSTRAINT-ENDURANCE",
            lambda e: e["properties"].pop("expression"),
        )
        self.assertRejected(model, "E-CONSTRAINT-NO-EXPRESSION")

    def test_reject_constraint_with_blank_expression(self):
        model = edit_element(
            extended_model(),
            "CONSTRAINT-ENDURANCE",
            lambda e: e["properties"].__setitem__("expression", "   "),
        )
        self.assertRejected(model, "E-CONSTRAINT-NO-EXPRESSION")

    def test_reject_constraint_with_multiline_expression(self):
        model = edit_element(
            extended_model(),
            "CONSTRAINT-ENDURANCE",
            lambda e: e["properties"].__setitem__("expression", "T = a\n  / b"),
        )
        self.assertRejected(model, "E-CONSTRAINT-EXPR-MULTILINE")

    def test_reject_constraint_without_parameters(self):
        model = edit_element(
            extended_model(),
            "CONSTRAINT-ENDURANCE",
            lambda e: e["properties"].pop("parameters"),
        )
        self.assertRejected(model, "E-CONSTRAINT-PARAMS-INVALID")

    def test_reject_constraint_with_empty_parameters(self):
        model = edit_element(
            extended_model(),
            "CONSTRAINT-ENDURANCE",
            lambda e: e["properties"].__setitem__("parameters", []),
        )
        self.assertRejected(model, "E-CONSTRAINT-PARAMS-INVALID")

    def test_reject_constraint_parameter_that_is_not_an_id_string(self):
        model = edit_element(
            extended_model(),
            "CONSTRAINT-ENDURANCE",
            lambda e: e["properties"].__setitem__("parameters", [42]),
        )
        self.assertRejected(model, "E-CONSTRAINT-PARAMS-INVALID")

    def test_reject_dangling_constraint_parameter(self):
        model = edit_element(
            extended_model(),
            "CONSTRAINT-ENDURANCE",
            lambda e: e["properties"].__setitem__("parameters", ["ATTR-NOPE"]),
        )
        self.assertRejected(model, "E-CONSTRAINT-PARAM-DANGLING")

    def test_reject_constraint_parameter_pointing_to_non_attribute(self):
        model = edit_element(
            extended_model(),
            "CONSTRAINT-ENDURANCE",
            lambda e: e["properties"].__setitem__("parameters", ["PART-USE-MOTOR"]),
        )
        self.assertRejected(model, "E-CONSTRAINT-PARAM-WRONGKIND")

    def test_reject_constraint_description_wrong_type(self):
        model = edit_element(
            extended_model(),
            "CONSTRAINT-ENDURANCE",
            lambda e: e["properties"].__setitem__("description", 42),
        )
        self.assertRejected(model, "E-PROP-TYPE")

    def test_reject_unknown_constraint_property(self):
        model = edit_element(
            extended_model(),
            "CONSTRAINT-ENDURANCE",
            lambda e: e["properties"].__setitem__("formula", "T = 1"),
        )
        self.assertRejected(model, "E-PROP-UNKNOWN")

    # --- Connection -------------------------------------------------------------------
    def test_reject_connection_without_source_ref(self):
        model = edit_element(
            extended_model(), "CONN-MOTOR-ESC", lambda e: e["properties"].pop("sourceRef")
        )
        self.assertRejected(model, "E-PROP-REQUIRED")

    def test_reject_connection_without_flow_kind(self):
        model = edit_element(
            extended_model(), "CONN-MOTOR-ESC", lambda e: e["properties"].pop("flowKind")
        )
        self.assertRejected(model, "E-PROP-REQUIRED")

    def test_reject_connection_without_target_ref(self):
        model = edit_element(
            extended_model(), "CONN-MOTOR-ESC", lambda e: e["properties"].pop("targetRef")
        )
        self.assertRejected(model, "E-PROP-REQUIRED")

    def test_reject_connection_with_invented_flow_kind(self):
        model = edit_element(
            extended_model(),
            "CONN-MOTOR-ESC",
            lambda e: e["properties"].__setitem__("flowKind", "magic"),
        )
        self.assertRejected(model, "E-ENUM-INVALID")

    def test_reject_dangling_connection_endpoint(self):
        model = edit_element(
            extended_model(),
            "CONN-MOTOR-ESC",
            lambda e: e["properties"].__setitem__("sourceRef", "PART-USE-NOPE"),
        )
        self.assertRejected(model, "E-CONNECTION-ENDPOINT-DANGLING")

    def test_reject_connection_endpoint_pointing_to_non_part_usage(self):
        model = edit_element(
            extended_model(),
            "CONN-MOTOR-ESC",
            lambda e: e["properties"].__setitem__("sourceRef", "PART-DEF-MOTOR"),
        )
        self.assertRejected(model, "E-CONNECTION-ENDPOINT-WRONGKIND")

    def test_reject_connection_with_identical_endpoints(self):
        model = edit_element(
            extended_model(),
            "CONN-MOTOR-ESC",
            lambda e: e["properties"].__setitem__("targetRef", "PART-USE-MOTOR"),
        )
        self.assertRejected(model, "E-CONNECTION-SELF")

    def test_reject_connection_endpoint_owned_by_someone_else(self):
        """端点必须与 Connection 同 owner：把端点挪到另一个 owner 下即报错。"""
        model = extended_model()
        for item in model["elements"]:
            if item["id"] == "PART-USE-MOTOR":
                item["owner"] = "PART-DEF-MOTOR"
        self.assertRejected(model, "E-CONNECTION-OWNER-MISMATCH")

    def test_reject_duplicate_connection_triple(self):
        model = extended_model()
        duplicate = copy.deepcopy(
            next(e for e in model["elements"] if e["id"] == "CONN-MOTOR-ESC")
        )
        duplicate["id"] = "CONN-MOTOR-ESC-COPY"
        duplicate["name"] = "motorToEscCopy"
        model["elements"].append(duplicate)
        self.assertRejected(model, "E-CONNECTION-DUP")

    def test_reject_connection_endpoint_wrong_type(self):
        model = edit_element(
            extended_model(),
            "CONN-MOTOR-ESC",
            lambda e: e["properties"].__setitem__("sourceRef", 3),
        )
        self.assertRejected(model, "E-PROP-TYPE")

    def test_unknown_kind_is_still_rejected(self):
        """增补不放松受控枚举：Port / Interface 之类仍必须被拒。"""
        model = edit_element(
            extended_model(),
            "CONN-MOTOR-ESC",
            lambda e: e.__setitem__("kind", "Port"),
        )
        self.assertRejected(model, "E-KIND-INVALID")


class TestErrorShape(unittest.TestCase):
    """返回结构契约：errors/warnings 每项必须含 code / element / message。"""

    def test_error_entries_have_required_keys(self):
        model = edit_element(base_model(), "REQ-A", lambda e: e["properties"].pop("acceptanceCriteria"))
        result = validate_model_json(model)
        for entry in result["errors"] + result["warnings"]:
            for key in ("code", "element", "message"):
                self.assertIn(key, entry)
                self.assertIsInstance(entry[key] if key != "element" else (entry[key] or ""), str)

    def test_result_is_json_serializable(self):
        import json

        json.dumps(validate_model_json(base_model()))
        json.dumps(validate_model_json(edit_element(base_model(), "REQ-A", lambda e: e.pop("owner"))))


class TestCoverageMeta(unittest.TestCase):
    """元测试：任务书点名的六类错误必须各有专属用例（防止后人删掉反例）。"""

    REQUIRED = {
        "缺 acceptanceCriteria": "E-REQ-NO-ACCEPTANCE",
        "relations.target 悬空": "E-REL-TARGET-DANGLING",
        "同 owner 命名冲突": "E-NAME-DUP",
        "kind 枚举自创": "E-KIND-INVALID",
        "数值字段写成字符串": "E-PROP-THRESHOLD-STRING",
        "typeRef 悬空": "E-PARTUSAGE-TYPEREF-DANGLING",
    }

    def test_every_required_error_family_is_actually_produced(self):
        produced = set()
        cases = {
            "E-REQ-NO-ACCEPTANCE": edit_element(
                base_model(), "REQ-A", lambda e: e["properties"].pop("acceptanceCriteria")
            ),
            "E-REL-TARGET-DANGLING": edit_element(
                base_model(), "REQ-A", lambda e: e["relations"][0].__setitem__("target", "NOPE")
            ),
            "E-NAME-DUP": edit_element(base_model(), "ATTR-A", lambda e: e.__setitem__("name", "Motor")),
            "E-KIND-INVALID": edit_element(base_model(), "ACT-A", lambda e: e.__setitem__("kind", "Bogus")),
            "E-PROP-THRESHOLD-STRING": edit_element(
                base_model(), "REQ-A", lambda e: e["properties"].__setitem__("minHours", "4 h")
            ),
            "E-PARTUSAGE-TYPEREF-DANGLING": edit_element(
                base_model(), "PART-USE-MOTOR", lambda e: e["properties"].__setitem__("typeRef", "NOPE")
            ),
        }
        for expected, model in cases.items():
            result = validate_model_json(model)
            self.assertFalse(result["ok"], msg="%s 的用例本该被拒绝" % expected)
            produced.update(codes(result))
        for label, code in self.REQUIRED.items():
            self.assertIn(code, produced, msg="缺少反例覆盖：%s（%s）" % (label, code))


if __name__ == "__main__":
    unittest.main(verbosity=2)
