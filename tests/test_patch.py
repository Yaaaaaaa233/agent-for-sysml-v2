"""二期 —— ``patch_model`` 增量编辑：原子性 / 回滚 / 级联 / diff 形状。

全部使用本文件自建的 fixture（不依赖标杆案例的元素计数，避免与并行任务互相牵制）。
"""

from __future__ import annotations

import copy
import json
import unittest

from _support import codes, validate_model_json
from tools.patch import patch_model


def fixture_model():
    """一个合法模型，覆盖「被引用 / 被验证 / 未满足 / 可删叶子」四种情形。"""
    return {
        "schema": "sysml-ir/v1",
        "package": "Demo",
        "elements": [
            {
                "id": "PART-DEF-MOTOR",
                "kind": "PartDefinition",
                "name": "Motor",
                "owner": "Demo",
                "properties": {"description": "无刷电机。"},
            },
            {
                "id": "PART-USE-MOTOR",
                "kind": "PartUsage",
                "name": "motorOne",
                "owner": "Demo",
                "properties": {"typeRef": "PART-DEF-MOTOR", "quantity": 2},
            },
            {
                "id": "REQ-A",
                "kind": "Requirement",
                "name": "ReqAlpha",
                "owner": "Demo",
                "properties": {
                    "text": "转速不低于 1000 rpm",
                    "acceptanceCriteria": "稳态转速 n >= 1000 rpm",
                    "verifyMethod": "simulation",
                },
                "relations": [
                    {
                        "type": "satisfiedBy",
                        "target": "PART-USE-MOTOR",
                        "rationale": "由电机选型满足",
                    }
                ],
            },
            {
                "id": "ACT-A",
                "kind": "ActionDefinition",
                "name": "ActAlpha",
                "owner": "Demo",
                "properties": {
                    "inputs": [{"name": "commandRpm", "typeRef": "Real", "unit": "rpm"}],
                    "outputs": [{"name": "measuredRpm", "typeRef": "Real", "unit": "rpm"}],
                },
                "relations": [
                    {"type": "verifies", "target": "REQ-A", "rationale": "仿真校验转速指标"}
                ],
            },
            {
                "id": "REQ-B",
                "kind": "Requirement",
                "name": "ReqBeta",
                "owner": "Demo",
                "properties": {
                    "text": "整机重量不超过 2 kg",
                    "acceptanceCriteria": "m <= 2 kg",
                },
            },
            {
                "id": "ATTR-A",
                "kind": "Attribute",
                "name": "ratedVoltage",
                "owner": "Demo",
                "properties": {"valueType": "Real", "defaultValue": 24.0, "unit": "V"},
            },
        ],
    }


def model_with_child():
    """在电机定义下挂一个 Attribute 子元素，用来验证 owner 级联。"""
    model = fixture_model()
    model["elements"].append(
        {
            "id": "ATTR-CHILD",
            "kind": "Attribute",
            "name": "motorMass",
            "owner": "PART-DEF-MOTOR",
            "properties": {"valueType": "Real", "defaultValue": 0.3, "unit": "kg"},
        }
    )
    return model


def new_attribute(element_id="ATTR-B", name="ratedCurrent"):
    return {
        "id": element_id,
        "kind": "Attribute",
        "name": name,
        "owner": "Demo",
        "properties": {"valueType": "Real", "defaultValue": 5.0, "unit": "A"},
    }


def get(model, element_id):
    for element in model["elements"]:
        if element.get("id") == element_id:
            return element
    raise KeyError(element_id)


class PatchTestCase(unittest.TestCase):
    def setUp(self):
        self.model = fixture_model()
        baseline = validate_model_json(self.model)
        self.assertTrue(baseline["ok"], msg=json.dumps(baseline["errors"], ensure_ascii=False))


class TestAddElement(PatchTestCase):
    def test_add_element_succeeds_and_returns_new_model(self):
        result = patch_model(self.model, [{"op": "add_element", "element": new_attribute()}])
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertEqual(set(result), {"ok", "model", "diff", "errors", "warnings"})
        self.assertIsNotNone(result["model"])
        self.assertEqual(get(result["model"], "ATTR-B")["name"], "ratedCurrent")
        self.assertEqual(len(result["diff"]), 1)
        self.assertEqual(
            {key: result["diff"][0][key] for key in ("change", "kind", "id")},
            {"change": "+", "kind": "element", "id": "ATTR-B"},
        )

    def test_add_element_does_not_mutate_input(self):
        snapshot = json.dumps(self.model, sort_keys=True, ensure_ascii=False)
        patch_model(self.model, [{"op": "add_element", "element": new_attribute()}])
        self.assertEqual(json.dumps(self.model, sort_keys=True, ensure_ascii=False), snapshot)

    def test_duplicate_id_is_rejected_atomically(self):
        duplicate = new_attribute(element_id="ATTR-A")
        result = patch_model(self.model, [{"op": "add_element", "element": duplicate}])
        self.assertFalse(result["ok"])
        self.assertIsNone(result["model"])
        self.assertIn("E-PATCH-ID-DUP", codes(result))
        self.assertEqual(result["diff"], [])

    def test_element_must_be_object(self):
        result = patch_model(self.model, [{"op": "add_element", "element": "nope"}])
        self.assertIn("E-PATCH-ELEMENT-INVALID", codes(result))
        self.assertIsNone(result["model"])

    def test_missing_element_id(self):
        element = new_attribute()
        del element["id"]
        result = patch_model(self.model, [{"op": "add_element", "element": element}])
        self.assertIn("E-PATCH-ID-MISSING", codes(result))

    def test_invalid_kind_is_caught_by_post_validation(self):
        element = new_attribute()
        element["kind"] = "BogusKind"
        result = patch_model(self.model, [{"op": "add_element", "element": element}])
        self.assertFalse(result["ok"])
        self.assertIn("E-PATCH-VALIDATE-FAILED", codes(result))
        self.assertIn("E-KIND-INVALID", codes(result))
        self.assertIsNone(result["model"])


class TestUpdateElement(PatchTestCase):
    def test_update_replaces_whole_element(self):
        replacement = copy.deepcopy(get(self.model, "ATTR-A"))
        replacement["name"] = "ratedVoltageBus"
        replacement["properties"]["defaultValue"] = 48.0
        result = patch_model(
            self.model, [{"op": "update_element", "id": "ATTR-A", "element": replacement}]
        )
        self.assertTrue(result["ok"], msg=result["errors"])
        updated = get(result["model"], "ATTR-A")
        self.assertEqual(updated["name"], "ratedVoltageBus")
        self.assertEqual(updated["properties"]["defaultValue"], 48.0)
        self.assertEqual(result["diff"][0]["change"], "~")
        self.assertEqual(result["diff"][0]["kind"], "element")
        self.assertIn("properties.defaultValue", result["diff"][0]["detail"])

    def test_id_mismatch_is_rejected(self):
        replacement = copy.deepcopy(get(self.model, "ATTR-A"))
        replacement["id"] = "ATTR-Z"
        result = patch_model(
            self.model, [{"op": "update_element", "id": "ATTR-A", "element": replacement}]
        )
        self.assertIn("E-PATCH-ID-MISMATCH", codes(result))
        self.assertIsNone(result["model"])

    def test_unknown_id_is_rejected(self):
        result = patch_model(
            self.model,
            [{"op": "update_element", "id": "NOPE", "element": {"id": "NOPE"}}],
        )
        self.assertIn("E-PATCH-ID-NOTFOUND", codes(result))

    def test_update_element_must_be_object(self):
        result = patch_model(
            self.model, [{"op": "update_element", "id": "ATTR-A", "element": []}]
        )
        self.assertIn("E-PATCH-ELEMENT-INVALID", codes(result))


class TestRemoveElement(PatchTestCase):
    def test_remove_unreferenced_leaf(self):
        result = patch_model(self.model, [{"op": "remove_element", "id": "ATTR-A"}])
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertNotIn("ATTR-A", [element["id"] for element in result["model"]["elements"]])
        self.assertEqual(result["diff"][0]["change"], "-")
        self.assertEqual(result["diff"][0]["id"], "ATTR-A")

    def test_default_mode_rejects_referenced_element_with_e_ref_dependent(self):
        result = patch_model(self.model, [{"op": "remove_element", "id": "PART-USE-MOTOR"}])
        self.assertFalse(result["ok"])
        self.assertIsNone(result["model"])
        self.assertIn("E-REF-DEPENDENT", codes(result))
        self.assertEqual(result["diff"], [])
        messages = " ".join(item["message"] for item in result["errors"])
        self.assertIn("REQ-A", messages)

    def test_default_mode_rejects_type_ref_dependency(self):
        result = patch_model(self.model, [{"op": "remove_element", "id": "PART-DEF-MOTOR"}])
        self.assertIn("E-REF-DEPENDENT", codes(result))
        messages = " ".join(item["message"] for item in result["errors"])
        self.assertIn("properties.typeRef", messages)

    def test_default_mode_rejects_owner_dependency(self):
        result = patch_model(model_with_child(), [{"op": "remove_element", "id": "PART-DEF-MOTOR"}])
        self.assertIn("E-REF-DEPENDENT", codes(result))
        messages = " ".join(item["message"] for item in result["errors"])
        self.assertIn("ATTR-CHILD", messages)
        self.assertIn("owner", messages)

    def test_unknown_id(self):
        result = patch_model(self.model, [{"op": "remove_element", "id": "NOPE"}])
        self.assertIn("E-PATCH-ID-NOTFOUND", codes(result))

    def test_cascade_strips_relations_and_removes_type_ref_dependents(self):
        result = patch_model(
            self.model, [{"op": "remove_element", "id": "PART-DEF-MOTOR", "cascade": True}]
        )
        self.assertTrue(result["ok"], msg=result["errors"])
        remaining = {element["id"] for element in result["model"]["elements"]}
        self.assertNotIn("PART-DEF-MOTOR", remaining)
        self.assertNotIn("PART-USE-MOTOR", remaining)
        self.assertEqual(get(result["model"], "REQ-A")["relations"], [])

        changed = {(entry["change"], entry["kind"], entry["id"]) for entry in result["diff"]}
        self.assertIn(("-", "element", "PART-DEF-MOTOR"), changed)
        self.assertIn(("-", "element", "PART-USE-MOTOR"), changed)
        self.assertIn(("-", "relation", "REQ-A"), changed)
        # 每条级联都单独出现在 diff 里
        self.assertEqual(len(result["diff"]), 3)

    def test_cascade_removes_owner_subtree(self):
        result = patch_model(
            model_with_child(),
            [{"op": "remove_element", "id": "PART-DEF-MOTOR", "cascade": True}],
        )
        self.assertTrue(result["ok"], msg=result["errors"])
        remaining = {element["id"] for element in result["model"]["elements"]}
        self.assertNotIn("ATTR-CHILD", remaining)
        changed = {entry["id"] for entry in result["diff"] if entry["kind"] == "element"}
        self.assertIn("ATTR-CHILD", changed)

    def test_cascade_keeps_model_valid(self):
        result = patch_model(
            self.model, [{"op": "remove_element", "id": "REQ-A", "cascade": True}]
        )
        self.assertTrue(result["ok"], msg=result["errors"])
        check = validate_model_json(result["model"])
        self.assertTrue(check["ok"], msg=json.dumps(check["errors"], ensure_ascii=False))


class TestRelations(PatchTestCase):
    def test_add_relation(self):
        result = patch_model(
            self.model,
            [
                {
                    "op": "add_relation",
                    "id": "REQ-B",
                    "relation": {
                        "type": "satisfiedBy",
                        "target": "PART-USE-MOTOR",
                        "rationale": "电机选型满足重量约束",
                    },
                }
            ],
        )
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertTrue(get(result["model"], "REQ-B")["relations"])
        self.assertEqual(result["diff"][0]["change"], "+")
        self.assertEqual(result["diff"][0]["kind"], "relation")
        self.assertEqual(result["diff"][0]["id"], "REQ-B")

    def test_add_relation_creates_relations_field_when_absent(self):
        result = patch_model(
            self.model,
            [
                {
                    "op": "add_relation",
                    "id": "ATTR-A",
                    "relation": {"type": "refines", "target": "REQ-A", "rationale": "参数细化"},
                }
            ],
        )
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertEqual(len(get(result["model"], "ATTR-A")["relations"]), 1)

    def test_duplicate_relation_is_rejected(self):
        result = patch_model(
            self.model,
            [
                {
                    "op": "add_relation",
                    "id": "REQ-A",
                    "relation": {
                        "type": "satisfiedBy",
                        "target": "PART-USE-MOTOR",
                        "rationale": "重复",
                    },
                }
            ],
        )
        self.assertIn("E-PATCH-REL-DUP", codes(result))
        self.assertIsNone(result["model"])

    def test_add_relation_unknown_host(self):
        result = patch_model(
            self.model,
            [
                {
                    "op": "add_relation",
                    "id": "NOPE",
                    "relation": {"type": "refines", "target": "REQ-A", "rationale": "r"},
                }
            ],
        )
        self.assertIn("E-PATCH-ID-NOTFOUND", codes(result))

    def test_add_relation_requires_type_and_target(self):
        result = patch_model(
            self.model,
            [{"op": "add_relation", "id": "REQ-B", "relation": {"rationale": "缺字段"}}],
        )
        self.assertIn("E-PATCH-REL-INVALID", codes(result))

    def test_dangling_relation_target_fails_validation_and_rolls_back(self):
        result = patch_model(
            self.model,
            [
                {
                    "op": "add_relation",
                    "id": "REQ-B",
                    "relation": {
                        "type": "satisfiedBy",
                        "target": "PART-USE-GHOST",
                        "rationale": "悬空引用",
                    },
                }
            ],
        )
        self.assertFalse(result["ok"])
        self.assertIn("E-PATCH-VALIDATE-FAILED", codes(result))
        self.assertIn("E-REL-TARGET-DANGLING", codes(result))
        self.assertIsNone(result["model"])
        self.assertIn("已回滚", result["diff"][0]["detail"])

    def test_remove_relation(self):
        result = patch_model(
            self.model,
            [{"op": "remove_relation", "id": "REQ-A", "type": "satisfiedBy", "target": "PART-USE-MOTOR"}],
        )
        self.assertTrue(result["ok"], msg=result["errors"])
        self.assertEqual(get(result["model"], "REQ-A")["relations"], [])
        self.assertEqual(result["diff"][0]["change"], "-")
        self.assertEqual(result["diff"][0]["id"], "REQ-A")
        self.assertIn("satisfiedBy", result["diff"][0]["detail"])

    def test_remove_missing_relation(self):
        result = patch_model(
            self.model,
            [{"op": "remove_relation", "id": "REQ-A", "type": "verifies", "target": "REQ-B"}],
        )
        self.assertIn("E-PATCH-REL-NOTFOUND", codes(result))

    def test_remove_relation_unknown_host(self):
        result = patch_model(
            self.model,
            [{"op": "remove_relation", "id": "NOPE", "type": "refines", "target": "REQ-A"}],
        )
        self.assertIn("E-PATCH-ID-NOTFOUND", codes(result))


class TestAtomicity(PatchTestCase):
    def test_bad_op_after_good_op_rolls_back_everything(self):
        snapshot = json.dumps(self.model, sort_keys=True, ensure_ascii=False)
        result = patch_model(
            self.model,
            [
                {"op": "add_element", "element": new_attribute()},
                {"op": "remove_element", "id": "NOPE"},
            ],
        )
        self.assertFalse(result["ok"])
        self.assertIsNone(result["model"])
        self.assertIn("E-PATCH-ID-NOTFOUND", codes(result))
        self.assertEqual(len(result["diff"]), 1)
        self.assertIn("已回滚", result["diff"][0]["detail"])
        self.assertEqual(json.dumps(self.model, sort_keys=True, ensure_ascii=False), snapshot)

    def test_validation_failure_returns_no_model_and_rollback_diff(self):
        snapshot = json.dumps(self.model, sort_keys=True, ensure_ascii=False)
        broken = copy.deepcopy(get(self.model, "REQ-A"))
        broken["properties"]["text"] = ""
        result = patch_model(
            self.model,
            [
                {"op": "add_element", "element": new_attribute()},
                {"op": "update_element", "id": "REQ-A", "element": broken},
            ],
        )
        self.assertFalse(result["ok"])
        self.assertIsNone(result["model"])
        self.assertEqual(result["errors"][0]["code"], "E-PATCH-VALIDATE-FAILED")
        self.assertIn("E-REQ-NO-TEXT", codes(result))
        self.assertEqual(len(result["diff"]), 2)
        for entry in result["diff"]:
            self.assertIn("已回滚", entry["detail"])
        self.assertEqual(json.dumps(self.model, sort_keys=True, ensure_ascii=False), snapshot)

    def test_validate_false_skips_post_validation(self):
        element = new_attribute()
        element["kind"] = "BogusKind"
        result = patch_model(
            self.model, [{"op": "add_element", "element": element}], validate=False
        )
        self.assertTrue(result["ok"])
        self.assertEqual(get(result["model"], "ATTR-B")["kind"], "BogusKind")
        self.assertEqual(result["warnings"], [])


class TestInputHandling(PatchTestCase):
    def test_accepts_json_string_model(self):
        result = patch_model(json.dumps(self.model), [{"op": "remove_element", "id": "ATTR-A"}])
        self.assertTrue(result["ok"], msg=result["errors"])

    def test_rejects_non_object_model(self):
        result = patch_model([], [])
        self.assertFalse(result["ok"])
        self.assertIn("E-PATCH-MODEL-INVALID", codes(result))
        self.assertIsNone(result["model"])

    def test_rejects_bad_json_string(self):
        result = patch_model("{oops", [])
        self.assertIn("E-PATCH-MODEL-INVALID", codes(result))

    def test_rejects_non_array_ops(self):
        result = patch_model(self.model, {"op": "remove_element", "id": "ATTR-A"})
        self.assertIn("E-PATCH-OPS-NOT-ARRAY", codes(result))
        self.assertIsNone(result["model"])

    def test_rejects_non_object_op(self):
        result = patch_model(self.model, ["add_element"])
        self.assertIn("E-PATCH-OP-INVALID", codes(result))

    def test_rejects_unknown_op(self):
        result = patch_model(self.model, [{"op": "rename_element", "id": "ATTR-A"}])
        self.assertIn("E-PATCH-UNKNOWN-OP", codes(result))

    def test_empty_ops_is_a_valid_noop(self):
        result = patch_model(self.model, [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["diff"], [])
        self.assertEqual(result["model"], self.model)

    def test_result_is_json_serializable(self):
        result = patch_model(
            self.model,
            [{"op": "add_element", "element": new_attribute()}],
        )
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
