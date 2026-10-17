"""T5 —— ``query_model`` 四种查询形态。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import base_model, edit_element, extended_model, golden_model, query_model


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
        # 注：原先这里用 "Constraint" 代表未知 kind；并行任务把 Constraint/Connection
        # 纳入受控枚举后，它已不再是未知值，故改成自造的 "BogusKind"（断言意图不变）。
        result = query_model(base_model(), kind="BogusKind")
        self.assertFalse(result["ok"])
        self.assertIn("受控枚举", result["error"])
        self.assertIn("PartDefinition", result["allowedKinds"])
        self.assertNotIn("BogusKind", result["allowedKinds"])

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


class TestReferrerEdges(unittest.TestCase):
    """review 遗留：``Constraint.parameters`` 与 ``Connection`` 端点也是引用边。

    ``referrers_of`` 原先只扫 ``relations.target`` 与 ``properties.typeRef``，
    于是「约束引用了这个参数」「连接从/到这个部件」都会被漏掉——追溯图上表现为
    元素孤立（``anti-patterns`` 第 14 条要抓的正是这种）。
    """

    def test_constraint_parameters_count_as_referrers(self):
        result = query_model(extended_model(), referrers_of="ATTR-A")
        edges = {(r["id"], r["via"]) for r in result["results"]}
        self.assertIn(("CONSTRAINT-ENDURANCE", "properties.parameters"), edges)
        # 参数数组里只出现一次，结果也不该重复计数
        matches = [r for r in result["results"] if r["id"] == "CONSTRAINT-ENDURANCE"]
        self.assertEqual(len(matches), 1)
        self.assertIsNone(matches[0]["rationale"])

    def test_connection_source_ref_counts_as_referrer(self):
        result = query_model(extended_model(), referrers_of="PART-USE-MOTOR")
        edges = {(r["id"], r["via"]) for r in result["results"]}
        self.assertIn(("CONN-MOTOR-ESC", "properties.sourceRef"), edges)
        # 原有的 relations 边不受影响
        self.assertIn(("REQ-A", "relations.satisfiedBy"), edges)

    def test_connection_target_ref_counts_as_referrer(self):
        result = query_model(extended_model(), referrers_of="PART-USE-ESC")
        edges = {(r["id"], r["via"]) for r in result["results"]}
        self.assertEqual(edges, {("CONN-MOTOR-ESC", "properties.targetRef")})
        self.assertEqual(result["count"], 1)

    def test_type_ref_edge_still_works_next_to_new_edges(self):
        result = query_model(extended_model(), referrers_of="PART-DEF-ESC")
        edges = {(r["id"], r["via"]) for r in result["results"]}
        self.assertIn(("PART-USE-ESC", "properties.typeRef"), edges)

    def test_owner_chain_is_not_a_referrer_edge(self):
        """owner 归属不算引用：否则每个元素的父链都会变成引用方。"""
        result = query_model(extended_model(), referrers_of="Demo")
        self.assertTrue(result["ok"])
        self.assertFalse(result["targetExists"])
        self.assertEqual(result["count"], 0)

    def test_unrelated_edges_are_not_counted(self):
        result = query_model(extended_model(), referrers_of="STATE-A")
        self.assertEqual(result["count"], 0)

    def test_new_edges_survive_path_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            path.write_text(json.dumps(extended_model(), ensure_ascii=False), encoding="utf-8")
            result = query_model(path=str(path), referrers_of="ATTR-A")
        self.assertEqual(result["results"][0]["id"], "CONSTRAINT-ENDURANCE")


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


class TestPathInput(unittest.TestCase):
    """试用反馈：query_model 支持服务端本地文件路径（与 model 二选一）。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = Path(self._tmpdir.name) / "model.json"
        self.path.write_text(json.dumps(base_model(), ensure_ascii=False), encoding="utf-8")

    def test_loads_model_from_path(self):
        via_path = query_model(path=str(self.path), keyword="Motor")
        direct = query_model(base_model(), keyword="Motor")
        self.assertTrue(via_path["ok"])
        self.assertEqual(via_path["results"], direct["results"])
        self.assertEqual(via_path["count"], direct["count"])

    def test_path_works_for_referrers_mode(self):
        result = query_model(path=str(self.path), referrers_of="PART-USE-MOTOR")
        self.assertEqual(result["mode"], "referrers")
        self.assertEqual(result["results"][0]["id"], "REQ-A")

    def test_path_works_for_duplicates_mode(self):
        result = query_model(path=str(self.path), duplicates=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["duplicateIds"], [])

    def test_missing_file_reports_error_without_traceback(self):
        missing = str(Path(self._tmpdir.name) / "nope.json")
        result = query_model(path=missing)
        self.assertFalse(result["ok"])
        self.assertEqual(result["mode"], "error")
        self.assertIn("不存在", result["error"])
        self.assertEqual(result["path"], missing)

    def test_model_and_path_are_mutually_exclusive(self):
        result = query_model(base_model(), path=str(self.path))
        self.assertFalse(result["ok"])
        self.assertIn("二选一", result["error"])

    def test_neither_model_nor_path_is_rejected(self):
        result = query_model()
        self.assertFalse(result["ok"])
        self.assertIn("缺少输入", result["error"])

    def test_malformed_json_file(self):
        bad = Path(self._tmpdir.name) / "bad.json"
        bad.write_text("{oops", encoding="utf-8")
        result = query_model(path=str(bad))
        self.assertFalse(result["ok"])
        self.assertIn("不是合法 JSON", result["error"])

    def test_top_level_not_object(self):
        bad = Path(self._tmpdir.name) / "array.json"
        bad.write_text("[1, 2, 3]", encoding="utf-8")
        result = query_model(path=str(bad))
        self.assertFalse(result["ok"])
        self.assertIn("顶层必须是 JSON 对象", result["error"])

    def test_directory_path(self):
        result = query_model(path=self._tmpdir.name)
        self.assertFalse(result["ok"])
        self.assertIn("目录", result["error"])

    def test_empty_path_string(self):
        result = query_model(path="   ")
        self.assertFalse(result["ok"])
        self.assertIn("非空字符串", result["error"])

    def test_non_string_path(self):
        result = query_model(path=123)
        self.assertFalse(result["ok"])
        self.assertIn("非空字符串", result["error"])

    def test_accepts_pathlib_path(self):
        """契约写的是字符串，但 pathlib.Path 顺手也接受（本地脚本常用）。"""
        result = query_model(path=self.path, kind="Requirement")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)

    def test_path_does_not_leak_into_success_payload(self):
        result = query_model(path=str(self.path), kind="Requirement")
        self.assertNotIn("path", result)
        self.assertEqual(result["count"], 1)


def env_with_root(root):
    """构造一个「只把 ``SYSML_QUERY_ROOT`` 设成 ``root``」的环境变量上下文。

    ``clear=True`` 会先清空再恢复，退出时把整个 environ 还原——不会把变量漏给其他用例。
    """
    values = {key: value for key, value in os.environ.items() if key != "SYSML_QUERY_ROOT"}
    if root is not None:
        values["SYSML_QUERY_ROOT"] = str(root)
    return mock.patch.dict(os.environ, values, clear=True)


class TestQueryRootSandbox(unittest.TestCase):
    """安全 review：``SYSML_QUERY_ROOT`` 设置后限制 ``path`` 的可读目录。

    未设置时保持原行为（不限制）；设置后按**解析符号链接之后**的路径比较，
    避免用软链接逃逸。
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp = Path(self._tmpdir.name)
        self.root = self.tmp / "data"
        self.root.mkdir()
        self.inside = self.root / "model.json"
        self.inside.write_text(json.dumps(base_model(), ensure_ascii=False), encoding="utf-8")
        self.outside = self.tmp / "outside.json"
        self.outside.write_text(json.dumps(base_model(), ensure_ascii=False), encoding="utf-8")

    def test_allows_path_inside_root(self):
        with env_with_root(self.root):
            result = query_model(path=str(self.inside), kind="Requirement")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)

    def test_allows_root_itself(self):
        """含根本身：不报「越界」，只在后面按「指向目录」报错。"""
        with env_with_root(self.root):
            result = query_model(path=str(self.root))
        self.assertFalse(result["ok"])
        self.assertIn("目录", result["error"])
        self.assertNotIn("E-QUERY-PATH-OUTSIDE-ROOT", result["error"])

    def test_rejects_path_outside_root(self):
        with env_with_root(self.root):
            result = query_model(path=str(self.outside))
        self.assertFalse(result["ok"])
        self.assertEqual(result["mode"], "error")
        self.assertEqual(result["results"], [])
        self.assertIn("E-QUERY-PATH-OUTSIDE-ROOT", result["error"])
        self.assertEqual(result["path"], str(self.outside))

    def test_rejects_symlink_escape(self):
        link = self.root / "escape.json"
        link.symlink_to(self.outside)
        with env_with_root(self.root):
            result = query_model(path=str(link))
        self.assertFalse(result["ok"])
        self.assertIn("E-QUERY-PATH-OUTSIDE-ROOT", result["error"])

    def test_allows_symlink_that_stays_inside_root(self):
        link = self.root / "alias.json"
        link.symlink_to(self.inside)
        with env_with_root(self.root):
            result = query_model(path=str(link), kind="Requirement")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)

    def test_missing_file_inside_root_reports_not_found(self):
        with env_with_root(self.root):
            result = query_model(path=str(self.root / "nope.json"))
        self.assertFalse(result["ok"])
        self.assertIn("不存在", result["error"])
        self.assertNotIn("E-QUERY-PATH-OUTSIDE-ROOT", result["error"])

    def test_unset_root_keeps_path_unrestricted(self):
        with env_with_root(None):
            result = query_model(path=str(self.outside), kind="Requirement")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)

    def test_blank_root_is_treated_as_unset(self):
        with env_with_root("   "):
            result = query_model(path=str(self.outside), kind="Requirement")
        self.assertTrue(result["ok"])

    def test_root_does_not_change_payload_shape(self):
        with env_with_root(self.root):
            result = query_model(path=str(self.inside), kind="Requirement")
        self.assertEqual(set(result), {"ok", "mode", "package", "keyword", "kind",
                                       "count", "truncated", "results"})


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
