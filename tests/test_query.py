"""T5 —— ``query_model`` 四种查询形态。"""

from __future__ import annotations

import json
import unittest

from _support import base_model, edit_element, golden_model, query_model


class TestSearch(unittest.TestCase):
    def test_lists_all_elements_without_filter(self):
        result = query_model(base_model())
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "elements")
        self.assertEqual(result["count"], len(base_model()["elements"]))

    def test_filter_by_kind(self):
        result = query_model(base_model(), kind="Requirement")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["id"], "REQ-A")

    def test_filter_by_unknown_kind_is_rejected(self):
        result = query_model(base_model(), kind="Constraint")
        self.assertFalse(result["ok"])
        self.assertIn("受控枚举", result["error"])
        self.assertIn("PartDefinition", result["allowedKinds"])
        self.assertNotIn("Constraint", result["allowedKinds"])

    def test_keyword_matches_name(self):
        result = query_model(base_model(), keyword="motor")
        self.assertGreaterEqual(result["count"], 1)
        self.assertIn("PART-USE-MOTOR", [r["id"] for r in result["results"]])

    def test_keyword_matches_properties_text(self):
        """关键字要能命中 properties 里的中文（需求正文）。"""
        result = query_model(base_model(), keyword="转速")
        self.assertIn("REQ-A", [r["id"] for r in result["results"]])

    def test_keyword_is_case_insensitive(self):
        lower = query_model(base_model(), keyword="req-a")
        upper = query_model(base_model(), keyword="REQ-A")
        self.assertEqual(lower["count"], upper["count"])
        self.assertIn("REQ-A", [r["id"] for r in lower["results"]])
        self.assertEqual(query_model(base_model(), keyword="ReqAlpha")["count"], 1)

    def test_keyword_matches_relations_too(self):
        """关键字也扫 relations——否则「谁提到过这个 id」就查不到。"""
        result = query_model(base_model(), keyword="REQ-A")
        matched = {r["id"] for r in result["results"]}
        self.assertIn("REQ-A", matched)  # 自身
        self.assertIn("ACT-A", matched)  # 通过 verifies.target 命中

    def test_query_alias_matches_keyword(self):
        a = query_model(base_model(), keyword="Motor")
        b = query_model(base_model(), query="Motor")
        self.assertEqual(a["count"], b["count"])
        self.assertEqual(a["results"], b["results"])

    def test_limit_truncates_and_flags(self):
        result = query_model(golden_model(), limit=3)
        self.assertEqual(result["count"], len(golden_model()["elements"]))
        self.assertEqual(len(result["results"]), 3)
        self.assertTrue(result["truncated"])

    def test_details_returns_full_element(self):
        result = query_model(base_model(), kind="Attribute", details=True)
        self.assertIn("properties", result["results"][0]["element"])

    def test_result_is_json_serializable(self):
        json.dumps(query_model(golden_model(), details=True))


class TestReferrers(unittest.TestCase):
    def test_finds_relation_referrer(self):
        result = query_model(base_model(), referrers_of="PART-USE-MOTOR")
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "referrers")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["id"], "REQ-A")
        self.assertEqual(result["results"][0]["via"], "relations.satisfiedBy")

    def test_finds_type_ref_referrer(self):
        result = query_model(base_model(), referrers_of="PART-DEF-MOTOR")
        self.assertEqual(result["results"][0]["via"], "properties.typeRef")
        self.assertEqual(result["results"][0]["id"], "PART-USE-MOTOR")

    def test_unknown_id_reports_not_exists_but_ok(self):
        result = query_model(base_model(), referrers_of="NOPE")
        self.assertTrue(result["ok"])
        self.assertFalse(result["targetExists"])
        self.assertEqual(result["count"], 0)

    def test_golden_power_chain_is_referenced(self):
        """标杆案例里功率链被两条需求与整机分解关系引用。"""
        result = query_model(golden_model(), referrers_of="PART-POWER-CHAIN")
        referrers = {r["id"] for r in result["results"]}
        self.assertIn("REQ-MISSION-ENDURANCE", referrers)
        self.assertIn("REQ-POWER-BUDGET", referrers)
        self.assertIn("PART-STRUCT-SYSTEM", referrers)
        self.assertIn("PART-USAGE-POWER-CHAIN", referrers)

    def test_golden_battery_pack_satisfies_cruise_endurance(self):
        result = query_model(golden_model(), referrers_of="PART-BATTERY-PACK")
        referrers = {r["id"] for r in result["results"]}
        self.assertIn("REQ-CRUISE-ENDURANCE", referrers)


class TestDuplicates(unittest.TestCase):
    def test_no_duplicates_in_base_model(self):
        result = query_model(base_model(), duplicates=True)
        self.assertEqual(result["duplicateIds"], [])
        self.assertEqual(result["duplicateNames"], [])
        self.assertEqual(result["count"], 0)

    def test_detects_duplicate_name(self):
        model = edit_element(base_model(), "ATTR-A", lambda e: e.__setitem__("name", "Motor"))
        result = query_model(model, duplicates=True)
        self.assertEqual(len(result["duplicateNames"]), 1)
        entry = result["duplicateNames"][0]
        self.assertEqual(entry["owner"], "Demo")
        self.assertEqual(entry["name"], "Motor")
        self.assertEqual(sorted(entry["ids"]), ["ATTR-A", "PART-DEF-MOTOR"])

    def test_detects_duplicate_id(self):
        model = edit_element(base_model(), "ACT-A", lambda e: e.__setitem__("id", "REQ-A"))
        result = query_model(model, duplicates=True)
        self.assertIn("REQ-A", result["duplicateIds"])


class TestUnsatisfied(unittest.TestCase):
    def test_none_unsatisfied_in_base_model(self):
        result = query_model(base_model(), unsatisfied_requirements=True)
        self.assertEqual(result["count"], 0)

    def test_none_unsatisfied_in_golden_case(self):
        """标杆案例里每条需求都必须有 satisfiedBy——不允许出现没人满足的需求。"""
        result = query_model(golden_model(), unsatisfied_requirements=True)
        self.assertEqual(result["count"], 0, msg=json.dumps(result["results"], ensure_ascii=False))

    def test_lists_requirement_without_satisfied_by(self):
        model = edit_element(base_model(), "REQ-A", lambda e: e.__setitem__("relations", []))
        result = query_model(model, unsatisfied_requirements=True)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["id"], "REQ-A")
        self.assertIn("转速", result["results"][0]["text"])

    def test_ignores_relations_of_other_types(self):
        model = edit_element(
            base_model(),
            "REQ-A",
            lambda e: e.__setitem__(
                "relations", [{"type": "refines", "target": "ACT-A", "rationale": "r"}]
            ),
        )
        self.assertEqual(query_model(model, unsatisfied_requirements=True)["count"], 1)


class TestErrorHandling(unittest.TestCase):
    def test_rejects_non_object_model(self):
        result = query_model("not a model")
        self.assertFalse(result["ok"])

    def test_reports_invalid_json_string(self):
        result = query_model("{oops")
        self.assertFalse(result["ok"])
        self.assertIn("JSON", result["error"])

    def test_does_not_mutate_input(self):
        model = base_model()
        snapshot = json.dumps(model, sort_keys=True)
        query_model(model, details=True)
        self.assertEqual(json.dumps(model, sort_keys=True), snapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
