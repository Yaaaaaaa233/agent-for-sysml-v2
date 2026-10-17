"""二期 —— ``traceability`` 追溯矩阵：四种状态 / 缺口 / 影响面 BFS / Markdown。

全部使用本文件自建的 fixture（不依赖标杆案例的元素计数）。
"""

from __future__ import annotations

import json
import unittest

from _support import codes
from tools.trace import traceability


def fixture_model():
    """四条需求覆盖四种状态；一个 ActionDefinition 故意没有 verifies。"""
    return {
        "schema": "sysml-ir/v1",
        "package": "TraceDemo",
        "elements": [
            {
                "id": "PART-DEF-A",
                "kind": "PartDefinition",
                "name": "Motor",
                "owner": "TraceDemo",
                "properties": {"description": "电机。"},
            },
            {
                "id": "PART-USE-A",
                "kind": "PartUsage",
                "name": "motorOne",
                "owner": "TraceDemo",
                "properties": {"typeRef": "PART-DEF-A", "quantity": 2},
            },
            {
                "id": "ATTR-CHILD",
                "kind": "Attribute",
                "name": "motorMass",
                "owner": "PART-USE-A",
                "properties": {"valueType": "Real", "defaultValue": 0.3, "unit": "kg"},
            },
            {
                "id": "REQ-SV",
                "kind": "Requirement",
                "name": "ReqSatisfiedVerified",
                "owner": "TraceDemo",
                "properties": {
                    "text": "长" * 100,
                    "acceptanceCriteria": "n >= 1000 rpm",
                    "verifyMethod": "simulation",
                },
                "relations": [
                    {"type": "satisfiedBy", "target": "PART-USE-A", "rationale": "电机满足"}
                ],
            },
            {
                "id": "REQ-S",
                "kind": "Requirement",
                "name": "ReqSatisfiedOnly",
                "owner": "TraceDemo",
                "properties": {
                    "text": "整机重量不超过 2 kg",
                    "acceptanceCriteria": "m <= 2 kg",
                },
                "relations": [
                    {"type": "satisfiedBy", "target": "PART-USE-A", "rationale": "轻量化设计"}
                ],
            },
            {
                "id": "REQ-V",
                "kind": "Requirement",
                "name": "ReqVerifiedOnly",
                "owner": "TraceDemo",
                "properties": {
                    "text": "悬停时间不低于 20 min",
                    "acceptanceCriteria": "t >= 20 min",
                },
            },
            {
                "id": "REQ-U",
                "kind": "Requirement",
                "name": "ReqUnsatisfied",
                "owner": "TraceDemo",
                "properties": {
                    "text": "噪声不超过 70 dB",
                    "acceptanceCriteria": "L <= 70 dB",
                },
            },
            {
                "id": "ACT-V1",
                "kind": "ActionDefinition",
                "name": "ActVerifyOne",
                "owner": "TraceDemo",
                "properties": {
                    "inputs": [{"name": "commandRpm", "typeRef": "Real", "unit": "rpm"}],
                    "outputs": [{"name": "measuredRpm", "typeRef": "Real", "unit": "rpm"}],
                },
                "relations": [
                    {"type": "verifies", "target": "REQ-SV", "rationale": "仿真校验"},
                    {"type": "verifies", "target": "REQ-V", "rationale": "仿真校验"},
                ],
            },
            {
                "id": "ACT-V2",
                "kind": "ActionDefinition",
                "name": "ActVerifyTwo",
                "owner": "TraceDemo",
                "properties": {"inputs": [], "outputs": []},
                "relations": [
                    {"type": "verifies", "target": "REQ-SV", "rationale": "台架试验"}
                ],
            },
            {
                "id": "ACT-UNVERIFIED",
                "kind": "ActionDefinition",
                "name": "ActUnverified",
                "owner": "TraceDemo",
                "properties": {"inputs": [], "outputs": []},
            },
        ],
    }


def row(result, requirement_id):
    for item in result["matrix"]:
        if item["requirement"] == requirement_id:
            return item
    raise KeyError(requirement_id)


class TraceTestCase(unittest.TestCase):
    def setUp(self):
        self.model = fixture_model()


class TestMatrix(TraceTestCase):
    def test_return_shape(self):
        result = traceability(self.model)
        self.assertEqual(
            set(result), {"ok", "matrix", "gaps", "impact", "content", "errors"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["errors"], [])
        self.assertIsNone(result["impact"])
        self.assertIsNone(result["content"])

    def test_four_statuses(self):
        result = traceability(self.model)
        statuses = {item["requirement"]: item["status"] for item in result["matrix"]}
        self.assertEqual(statuses["REQ-SV"], "satisfied-and-verified")
        self.assertEqual(statuses["REQ-S"], "satisfied")
        self.assertEqual(statuses["REQ-V"], "verified-only")
        self.assertEqual(statuses["REQ-U"], "unsatisfied")
        self.assertEqual(
            set(statuses.values()),
            {"satisfied-and-verified", "satisfied", "verified-only", "unsatisfied"},
        )

    def test_row_fields(self):
        result = traceability(self.model)
        entry = row(result, "REQ-SV")
        self.assertEqual(
            set(entry),
            {"requirement", "name", "text_short", "satisfiedBy", "verifiedBy", "status"},
        )
        self.assertEqual(entry["name"], "ReqSatisfiedVerified")
        self.assertEqual(entry["satisfiedBy"], ["PART-USE-A"])
        self.assertEqual(entry["verifiedBy"], ["ACT-V1", "ACT-V2"])

    def test_text_short_is_truncated(self):
        entry = row(traceability(self.model), "REQ-SV")
        self.assertEqual(len(entry["text_short"]), 60)
        self.assertTrue(entry["text_short"].endswith("…"))

    def test_short_text_is_not_truncated(self):
        entry = row(traceability(self.model), "REQ-S")
        self.assertEqual(entry["text_short"], "整机重量不超过 2 kg")

    def test_verified_by_dedupes_same_relation(self):
        model = fixture_model()
        for element in model["elements"]:
            if element["id"] == "ACT-V1":
                element["relations"].append(
                    {"type": "verifies", "target": "REQ-SV", "rationale": "重复登记"}
                )
        entry = row(traceability(model), "REQ-SV")
        self.assertEqual(entry["verifiedBy"], ["ACT-V1", "ACT-V2"])

    def test_ignores_unknown_kinds(self):
        model = fixture_model()
        model["elements"].append(
            {
                "id": "BOGUS-X",
                "kind": "BogusKind",
                "name": "bogusX",
                "owner": "TraceDemo",
                "properties": {},
            }
        )
        result = traceability(model)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["matrix"]), 4)

    def test_accepts_json_string(self):
        result = traceability(json.dumps(self.model))
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["matrix"]), 4)


class TestGaps(TraceTestCase):
    def test_gaps(self):
        result = traceability(self.model)
        self.assertEqual(result["gaps"]["unsatisfied"], ["REQ-U", "REQ-V"])
        self.assertEqual(result["gaps"]["unverified_requirement"], ["REQ-S", "REQ-U"])
        self.assertEqual(result["gaps"]["unverified_action"], ["ACT-UNVERIFIED"])

    def test_no_requirements_means_empty_matrix(self):
        model = {
            "schema": "sysml-ir/v1",
            "package": "Empty",
            "elements": [
                {
                    "id": "PART-DEF-A",
                    "kind": "PartDefinition",
                    "name": "Motor",
                    "owner": "Empty",
                    "properties": {},
                }
            ],
        }
        result = traceability(model)
        self.assertTrue(result["ok"])
        self.assertEqual(result["matrix"], [])
        self.assertEqual(
            result["gaps"],
            {"unsatisfied": [], "unverified_requirement": [], "unverified_action": []},
        )


class TestImpact(TraceTestCase):
    def test_direct_and_transitive(self):
        result = traceability(self.model, focus="PART-DEF-A")
        impact = result["impact"]
        self.assertIsNotNone(impact)
        self.assertEqual(impact["id"], "PART-DEF-A")
        self.assertEqual(impact["direct"], ["PART-USE-A"])
        self.assertEqual(
            impact["transitive"],
            ["ACT-V1", "ACT-V2", "ATTR-CHILD", "REQ-S", "REQ-SV"],
        )
        self.assertEqual(impact["affected_requirements"], ["REQ-S", "REQ-SV"])

    def test_owner_edge_counts_as_reference(self):
        impact = traceability(self.model, focus="PART-USE-A")["impact"]
        self.assertIn("ATTR-CHILD", impact["direct"])
        self.assertEqual(impact["transitive"], ["ACT-V1", "ACT-V2"])

    def test_focus_requirement_includes_itself_in_affected(self):
        impact = traceability(self.model, focus="REQ-SV")["impact"]
        self.assertEqual(impact["direct"], ["ACT-V1", "ACT-V2"])
        self.assertEqual(impact["transitive"], [])
        self.assertEqual(impact["affected_requirements"], ["REQ-SV"])

    def test_multi_focus_union(self):
        impact = traceability(self.model, focus=["PART-DEF-A", "REQ-U"])["impact"]
        self.assertEqual(impact["id"], ["PART-DEF-A", "REQ-U"])
        self.assertEqual(impact["direct"], ["PART-USE-A"])
        self.assertEqual(impact["affected_requirements"], ["REQ-S", "REQ-SV", "REQ-U"])

    def test_focus_is_ignored_when_absent(self):
        self.assertIsNone(traceability(self.model)["impact"])

    def test_unknown_focus_id(self):
        result = traceability(self.model, focus="NOPE")
        self.assertFalse(result["ok"])
        self.assertIn("E-TRACE-FOCUS-NOTFOUND", codes(result))
        self.assertIsNone(result["impact"])

    def test_invalid_focus_types(self):
        for focus in (123, [], [123], ""):
            with self.subTest(focus=focus):
                result = traceability(self.model, focus=focus)
                self.assertFalse(result["ok"])
                self.assertIn("E-TRACE-FOCUS-INVALID", codes(result))


class TestMarkdown(TraceTestCase):
    def test_md_renders_table_statuses_and_gaps(self):
        result = traceability(self.model, fmt="md")
        content = result["content"]
        self.assertIsInstance(content, str)
        self.assertIn("# 追溯矩阵", content)
        self.assertIn("| 需求 id | 名称 | 需求摘要 | satisfiedBy | verifiedBy | 状态 |", content)
        for requirement_id in ("REQ-SV", "REQ-S", "REQ-V", "REQ-U"):
            self.assertIn(requirement_id, content)
        for status in ("satisfied-and-verified", "satisfied", "verified-only", "unsatisfied"):
            self.assertIn(status, content)
        self.assertIn("## 缺口", content)
        self.assertIn("ACT-UNVERIFIED", content)

    def test_md_without_focus_has_no_impact_section(self):
        content = traceability(self.model, fmt="md")["content"]
        self.assertNotIn("## 影响面", content)

    def test_md_with_focus_has_impact_section(self):
        content = traceability(self.model, focus="REQ-SV", fmt="md")["content"]
        self.assertIn("## 影响面", content)
        self.assertIn("ACT-V1", content)

    def test_json_fmt_has_no_content(self):
        self.assertIsNone(traceability(self.model, fmt="json")["content"])

    def test_invalid_fmt(self):
        result = traceability(self.model, fmt="xml")
        self.assertFalse(result["ok"])
        self.assertIn("E-TRACE-FMT-INVALID", codes(result))

    def test_empty_matrix_renders_placeholder_row(self):
        model = {
            "schema": "sysml-ir/v1",
            "package": "Empty",
            "elements": [
                {
                    "id": "PART-DEF-A",
                    "kind": "PartDefinition",
                    "name": "Motor",
                    "owner": "Empty",
                    "properties": {},
                }
            ],
        }
        content = traceability(model, fmt="md")["content"]
        self.assertIn("| — | — | — | — | — | — |", content)


class TestInputHandling(TraceTestCase):
    def test_invalid_json_string(self):
        result = traceability("{oops")
        self.assertFalse(result["ok"])
        self.assertIn("E-INPUT-NOT-JSON", codes(result))

    def test_non_object_model(self):
        result = traceability([])
        self.assertFalse(result["ok"])
        self.assertIn("E-ROOT-NOT-OBJECT", codes(result))
        self.assertEqual(result["matrix"], [])

    def test_non_array_elements_is_rejected(self):
        model = fixture_model()
        model["elements"] = "not-an-array"
        result = traceability(model)
        self.assertFalse(result["ok"])
        self.assertIn("E-TRACE-MODEL-INVALID", codes(result))
        self.assertEqual(result["matrix"], [])

    def test_does_not_mutate_input(self):
        snapshot = json.dumps(self.model, sort_keys=True, ensure_ascii=False)
        traceability(self.model, focus="PART-DEF-A", fmt="md")
        self.assertEqual(json.dumps(self.model, sort_keys=True, ensure_ascii=False), snapshot)

    def test_result_is_json_serializable(self):
        json.dumps(traceability(self.model, focus="PART-DEF-A", fmt="md"), ensure_ascii=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
