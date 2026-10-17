"""T10 —— ``export_simulink`` 的参数表 / 公式清单导出。

覆盖：三种格式的形状与转义、scope 过滤、确定性、非法入参、需求阈值标注、
空模型与缺字段的优雅降级。**不**断言标杆案例的元素/行数——标杆案例由并行
任务持续演进，计数写死会制造假失败。
"""

from __future__ import annotations

import copy
import csv
import io
import json
import unittest

from _support import golden_model

from tools.export import CSV_HEADER, FORMATS, SCOPES, export_simulink


def fixture_model():
    """自建小模型：覆盖逗号 / 引号 / 换行、嵌套 owner、Constraint、阈值。

    ``Constraint`` 与 ``Connection`` 在当前校验器里可能还不是受控 kind；本工具
    刻意不依赖校验器白名单，因此这里照常导出，用来证明「未知 kind 保持通用」。
    其中字符串默认值与公式**故意带逗号 / 引号 / 换行**，专门用来验证 CSV 转义；
    正式 IR 的 ``Constraint.expression`` 按 Schema 是单行文本。
    """
    return {
        "schema": "sysml-ir/v1",
        "package": "Demo",
        "elements": [
            {
                "id": "PART-DEF-FRAME",
                "kind": "PartDefinition",
                "name": "Frame",
                "owner": "Demo",
                "properties": {"description": "机身。"},
            },
            {
                "id": "ATTR-TOP",
                "kind": "Attribute",
                "name": "topParam",
                "owner": "Demo",
                "properties": {"valueType": "Real", "defaultValue": 1.5, "unit": "V"},
            },
            {
                "id": "ATTR-NESTED",
                "kind": "Attribute",
                "name": "nestedParam",
                "owner": "PART-DEF-FRAME",
                "properties": {"valueType": "Integer", "defaultValue": 8, "unit": "count"},
            },
            {
                "id": "ATTR-STRING",
                "kind": "Attribute",
                "name": "labelParam",
                "owner": "Demo",
                "properties": {"valueType": "String", "defaultValue": 'a,b"c\nd'},
            },
            {
                "id": "ATTR-PIPE",
                "kind": "Attribute",
                "name": "pipeParam",
                "owner": "Demo",
                "properties": {"valueType": "String", "defaultValue": "x|y\nz"},
            },
            {
                "id": "CONSTRAINT-1",
                "kind": "Constraint",
                "name": "powerLaw",
                "owner": "Demo",
                "properties": {
                    "expression": 'P = m * a, "check"\nnext',
                    "parameters": ["ATTR-TOP", "ATTR-NESTED", "ATTR-MISSING"],
                },
            },
            {
                "id": "REQ-1",
                "kind": "Requirement",
                "name": "SpeedReq",
                "owner": "Demo",
                "properties": {
                    "text": "转速不低于 1000 rpm",
                    "acceptanceCriteria": "n >= 1000 rpm",
                    "minSpeedRpm": 1000.0,
                    "minEnergy": {"value": 1200, "unit": "Wh"},
                    "flag": True,
                    "badThreshold": "4 h",
                },
            },
            {
                "id": "CONN-1",
                "kind": "Connection",
                "name": "linkOne",
                "owner": "Demo",
                "properties": {
                    "sourceRef": "PART-DEF-FRAME",
                    "targetRef": "PART-DEF-FRAME",
                    "flowKind": "power",
                },
            },
        ],
    }


def sparse_model():
    """缺字段 / 未知 kind / 非对象元素的降级样本。"""
    return {
        "package": "Sparse",
        "elements": [
            {
                "id": "ATTR-NOVALUE",
                "kind": "Attribute",
                "name": "namelessValue",
                "owner": "Sparse",
                "properties": {},
            },
            {
                "id": "CONSTRAINT-EMPTY",
                "kind": "Constraint",
                "name": "emptyConstraint",
                "owner": "Sparse",
                "properties": {},
            },
            {
                "id": "REQ-EMPTY",
                "kind": "Requirement",
                "name": "emptyReq",
                "owner": "Sparse",
                "properties": {"text": "t", "acceptanceCriteria": "a"},
            },
            {
                "id": "ODD",
                "kind": "MysteryKind",
                "name": "mystery",
                "owner": "Sparse",
                "properties": {"anything": 1},
            },
            "not-an-object",
        ],
    }


def rows_by_id(result, kind=None):
    return {
        row["id"]: row
        for row in result["rows"]
        if kind is None or row.get("kind") == kind
    }


def csv_rows(content):
    text = content.lstrip("\ufeff")
    return list(csv.DictReader(io.StringIO(text)))


class TestContract(unittest.TestCase):
    def test_return_shape_is_fixed(self):
        result = export_simulink(fixture_model())
        self.assertEqual(
            set(result), {"ok", "content", "rows", "notes", "errors"}
        )
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["content"], str)
        self.assertIsInstance(result["rows"], list)
        self.assertIsInstance(result["notes"], list)
        self.assertEqual(result["errors"], [])

    def test_accepts_json_string(self):
        model = fixture_model()
        direct = export_simulink(model, fmt="json")
        parsed = export_simulink(json.dumps(model, ensure_ascii=False), fmt="json")
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["rows"], direct["rows"])
        self.assertEqual(parsed["content"], direct["content"])

    def test_invalid_fmt(self):
        result = export_simulink(fixture_model(), fmt="xlsx")
        self.assertFalse(result["ok"])
        self.assertEqual(result["content"], "")
        self.assertEqual(result["rows"], [])
        self.assertEqual([e["code"] for e in result["errors"]], ["E-EXPORT-FMT"])

    def test_invalid_scope(self):
        result = export_simulink(fixture_model(), scope="everything")
        self.assertFalse(result["ok"])
        self.assertEqual([e["code"] for e in result["errors"]], ["E-EXPORT-SCOPE"])

    def test_invalid_fmt_and_scope_report_both(self):
        result = export_simulink(fixture_model(), fmt="yml", scope="bad")
        self.assertFalse(result["ok"])
        self.assertEqual(
            [e["code"] for e in result["errors"]],
            ["E-EXPORT-FMT", "E-EXPORT-SCOPE"],
        )

    def test_invalid_model(self):
        for bad in (None, 42, [], "not json"):
            result = export_simulink(bad)
            self.assertFalse(result["ok"], msg=repr(bad))
            self.assertEqual(result["errors"][0]["code"], "E-EXPORT-INPUT")

    def test_empty_model(self):
        empty = {"schema": "sysml-ir/v1", "package": "Empty", "elements": []}
        for fmt in FORMATS:
            result = export_simulink(empty, fmt=fmt)
            self.assertTrue(result["ok"], msg=fmt)
            self.assertEqual(result["rows"], [], msg=fmt)
            self.assertTrue(result["content"], msg=fmt)
            self.assertTrue(any("占位值" in note for note in result["notes"]), msg=fmt)

    def test_missing_elements_is_graceful(self):
        result = export_simulink({"schema": "sysml-ir/v1", "package": "Empty"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"], [])
        self.assertTrue(any("elements" in note for note in result["notes"]))

    def test_notes_explain_consumption_and_placeholder(self):
        result = export_simulink(fixture_model(), fmt="csv")
        notes = "\n".join(result["notes"])
        self.assertIn("readtable", notes)
        self.assertIn("Simulink.Parameter", notes)
        self.assertIn("占位值", notes)

    def test_notes_do_not_name_a_real_simulink_project(self):
        """红线：消费示例只能用中性占位名，不能出现真实模型/项目文件名。"""
        for fmt in FORMATS:
            result = export_simulink(fixture_model(), fmt=fmt)
            blob = result["content"] + "\n".join(result["notes"])
            for suffix in (".slx", ".mdl", ".slxp", ".prj"):
                self.assertNotIn(suffix, blob.lower(), msg=fmt)

    def test_all_outputs_are_json_serializable(self):
        for fmt in FORMATS:
            json.dumps(export_simulink(golden_model(), fmt=fmt), ensure_ascii=False)


class TestScope(unittest.TestCase):
    def setUp(self):
        self.model = fixture_model()

    def test_all_covers_three_row_kinds(self):
        result = export_simulink(self.model, scope="all")
        self.assertEqual(
            {row["kind"] for row in result["rows"]},
            {"Attribute", "Constraint", "RequirementThreshold"},
        )
        self.assertEqual(len(result["rows"]), 8)  # 4 参数 + 1 公式 + 3 阈值（自建样本）

    def test_attributes_only(self):
        result = export_simulink(self.model, scope="attributes")
        self.assertEqual({row["kind"] for row in result["rows"]}, {"Attribute"})
        self.assertEqual(
            {row["id"] for row in result["rows"]},
            {"ATTR-TOP", "ATTR-NESTED", "ATTR-STRING", "ATTR-PIPE"},
        )

    def test_constraints_only(self):
        result = export_simulink(self.model, scope="constraints")
        self.assertEqual({row["kind"] for row in result["rows"]}, {"Constraint"})
        self.assertEqual(result["rows"][0]["id"], "CONSTRAINT-1")

    def test_requirements_only(self):
        result = export_simulink(self.model, scope="requirements")
        self.assertEqual(
            {row["kind"] for row in result["rows"]}, {"RequirementThreshold"}
        )
        self.assertTrue(any("需求阈值，非部件参数" in n for n in result["notes"]))

    def test_allowed_scopes_are_stable(self):
        self.assertEqual(SCOPES, ("all", "attributes", "constraints", "requirements"))
        self.assertEqual(FORMATS, ("csv", "json", "md"))


class TestCsv(unittest.TestCase):
    def setUp(self):
        self.result = export_simulink(fixture_model(), fmt="csv")
        self.assertTrue(self.result["ok"])
        self.content = self.result["content"]

    def test_bom_and_fixed_header(self):
        self.assertTrue(self.content.startswith("\ufeff"))
        self.assertIn("\r\n", self.content)
        header = self.content.lstrip("\ufeff").split("\r\n")[0]
        self.assertEqual(header, ",".join(CSV_HEADER))

    def test_row_count_and_order(self):
        parsed = csv_rows(self.content)
        self.assertEqual(len(parsed), len(self.result["rows"]))
        keys = [(r["path"], r["name"], r["kind"], r["id"]) for r in parsed]
        self.assertEqual(keys, sorted(keys))

    def test_comma_quote_newline_are_escaped_and_roundtrip(self):
        parsed = {row["id"]: row for row in csv_rows(self.content)}
        self.assertEqual(parsed["ATTR-STRING"]["defaultValue"], 'a,b"c\nd')
        # 含逗号/引号/换行的字段必然被引号包起来（csv 模块的标准转义）
        self.assertIn('"a,b""c\nd"', self.content)

    def test_constraint_formula_and_parameters_roundtrip(self):
        parsed = {row["id"]: row for row in csv_rows(self.content)}
        row = parsed["CONSTRAINT-1"]
        self.assertEqual(row["kind"], "Constraint")
        self.assertEqual(row["defaultValue"], 'P = m * a, "check"\nnext')
        extra = json.loads(row["extra"])
        self.assertEqual(
            extra["parameters"], ["topParam", "nestedParam", "ATTR-MISSING"]
        )

    def test_threshold_row_is_annotated_in_extra(self):
        rows = [
            row
            for row in csv_rows(self.content)
            if row["kind"] == "RequirementThreshold" and row["name"] == "minSpeedRpm"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            json.loads(rows[0]["extra"])["note"], "需求阈值，非部件参数"
        )

    def test_known_values_are_preserved(self):
        parsed = {(row["id"], row["name"]): row for row in csv_rows(self.content)}
        self.assertEqual(parsed[("ATTR-TOP", "topParam")]["defaultValue"], "1.5")
        self.assertEqual(parsed[("ATTR-NESTED", "nestedParam")]["defaultValue"], "8")
        self.assertEqual(parsed[("REQ-1", "minSpeedRpm")]["defaultValue"], "1000.0")
        self.assertEqual(
            parsed[("REQ-1", "minEnergy")]["defaultValue"], "1200"
        )


class TestJson(unittest.TestCase):
    def setUp(self):
        self.result = export_simulink(fixture_model(), fmt="json")

    def test_content_parses_and_matches_rows(self):
        payload = json.loads(self.result["content"])
        self.assertEqual(set(payload), {"rows", "notes"})
        self.assertEqual(payload["rows"], self.result["rows"])
        self.assertEqual(payload["notes"], self.result["notes"])

    def test_constraint_keeps_expression_and_parameters(self):
        payload = json.loads(self.result["content"])
        row = [r for r in payload["rows"] if r["kind"] == "Constraint"][0]
        self.assertEqual(row["expression"], 'P = m * a, "check"\nnext')
        self.assertEqual(
            row["parameters"], ["topParam", "nestedParam", "ATTR-MISSING"]
        )

    def test_json_has_no_bom(self):
        self.assertFalse(self.result["content"].startswith("\ufeff"))


class TestMarkdown(unittest.TestCase):
    def setUp(self):
        self.result = export_simulink(fixture_model(), fmt="md")
        self.lines = self.result["content"].splitlines()

    def test_table_shape(self):
        self.assertEqual(self.lines[0], "| " + " | ".join(CSV_HEADER) + " |")
        self.assertTrue(self.lines[1].startswith("| ---"))
        self.assertEqual(len(self.lines), len(self.result["rows"]) + 2)

    def test_pipe_and_newline_are_escaped(self):
        self.assertIn("x\\|y<br>z", self.result["content"])
        self.assertNotIn("x|y\nz", self.result["content"])

    def test_constraint_row_shows_formula_and_parameters(self):
        line = [l for l in self.lines if "CONSTRAINT-1" in l][0]
        self.assertIn('P = m * a, "check"<br>next', line)
        self.assertIn('{"parameters":["topParam","nestedParam","ATTR-MISSING"]}', line)


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_content(self):
        model = fixture_model()
        for fmt in FORMATS:
            first = export_simulink(model, fmt=fmt)
            second = export_simulink(model, fmt=fmt)
            self.assertEqual(first["content"], second["content"], msg=fmt)
            self.assertEqual(first["rows"], second["rows"], msg=fmt)
            self.assertEqual(first["notes"], second["notes"], msg=fmt)

    def test_element_order_does_not_change_content(self):
        model = fixture_model()
        shuffled = copy.deepcopy(model)
        shuffled["elements"] = list(reversed(shuffled["elements"]))
        for fmt in FORMATS:
            self.assertEqual(
                export_simulink(model, fmt=fmt)["content"],
                export_simulink(shuffled, fmt=fmt)["content"],
                msg=fmt,
            )

    def test_does_not_mutate_input(self):
        model = fixture_model()
        snapshot = json.dumps(model, ensure_ascii=False, sort_keys=True)
        for fmt in FORMATS:
            export_simulink(model, fmt=fmt)
        self.assertEqual(json.dumps(model, ensure_ascii=False, sort_keys=True), snapshot)

    def test_scope_filter_does_not_leak_rows(self):
        model = fixture_model()
        all_rows = export_simulink(model, scope="all")["rows"]
        parts = []
        for scope in ("attributes", "constraints", "requirements"):
            parts.extend(export_simulink(model, scope=scope)["rows"])
        self.assertEqual(
            sorted(all_rows, key=lambda r: (r["path"], r["name"], r["kind"], r["id"])),
            sorted(parts, key=lambda r: (r["path"], r["name"], r["kind"], r["id"])),
        )


class TestRequirements(unittest.TestCase):
    def setUp(self):
        self.result = export_simulink(
            fixture_model(), fmt="json", scope="requirements"
        )
        self.rows = {row["name"]: row for row in self.result["rows"]}

    def test_threshold_types_and_units(self):
        self.assertEqual(self.rows["minSpeedRpm"]["valueType"], "Real")
        self.assertEqual(self.rows["minSpeedRpm"]["unit"], "")
        self.assertEqual(self.rows["minEnergy"]["valueType"], "Integer")
        self.assertEqual(self.rows["minEnergy"]["unit"], "Wh")
        self.assertEqual(self.rows["minEnergy"]["defaultValue"], 1200)
        self.assertEqual(self.rows["flag"]["valueType"], "Boolean")

    def test_threshold_path_contains_requirement(self):
        self.assertEqual(self.rows["minSpeedRpm"]["path"], "Demo.SpeedReq")
        self.assertEqual(self.rows["minSpeedRpm"]["id"], "REQ-1")

    def test_non_numeric_threshold_is_skipped_with_note(self):
        self.assertNotIn("badThreshold", self.rows)
        self.assertTrue(any("badThreshold" in n for n in self.result["notes"]))

    def test_single_threshold_annotation(self):
        hits = [n for n in self.result["notes"] if "需求阈值，非部件参数" in n]
        self.assertEqual(len(hits), 1)

    def test_threshold_rows_do_not_appear_in_attribute_scope(self):
        result = export_simulink(fixture_model(), scope="attributes")
        self.assertNotIn("RequirementThreshold", {r["kind"] for r in result["rows"]})


class TestDegrade(unittest.TestCase):
    def setUp(self):
        self.model = sparse_model()
        self.result = export_simulink(self.model, fmt="json")
        self.rows = rows_by_id(self.result)

    def test_ok_despite_missing_fields(self):
        self.assertTrue(self.result["ok"])
        self.assertEqual(self.result["errors"], [])

    def test_missing_attribute_fields_are_empty_with_note(self):
        row = self.rows["ATTR-NOVALUE"]
        self.assertEqual(row["valueType"], "")
        self.assertEqual(row["defaultValue"], "")
        self.assertEqual(row["unit"], "")
        joined = "\n".join(self.result["notes"])
        self.assertIn("ATTR-NOVALUE", joined)
        self.assertIn("valueType", joined)
        self.assertIn("defaultValue", joined)

    def test_missing_constraint_fields_degrade_to_empty(self):
        row = self.rows["CONSTRAINT-EMPTY"]
        self.assertEqual(row["expression"], "")
        self.assertEqual(row["parameters"], [])
        joined = "\n".join(self.result["notes"])
        self.assertIn("expression", joined)
        self.assertIn("parameters", joined)

    def test_unknown_kind_is_ignored(self):
        self.assertNotIn("ODD", self.rows)

    def test_non_object_element_is_skipped_with_note(self):
        self.assertTrue(any("不是 JSON 对象" in n for n in self.result["notes"]))

    def test_missing_owner_path_degrades(self):
        model = {
            "package": "Demo",
            "elements": [
                {
                    "id": "ATTR-GHOST",
                    "kind": "Attribute",
                    "name": "ghostParam",
                    "owner": "GHOST-OWNER",
                    "properties": {"valueType": "Real", "defaultValue": 1.0},
                }
            ],
        }
        result = export_simulink(model, fmt="json")
        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"][0]["path"], "GHOST-OWNER")
        self.assertTrue(any("GHOST-OWNER" in n for n in result["notes"]))

    def test_owner_cycle_terminates(self):
        model = {
            "package": "Demo",
            "elements": [
                {
                    "id": "PART-A",
                    "kind": "PartDefinition",
                    "name": "A",
                    "owner": "PART-B",
                    "properties": {},
                },
                {
                    "id": "PART-B",
                    "kind": "PartDefinition",
                    "name": "B",
                    "owner": "PART-A",
                    "properties": {},
                },
                {
                    "id": "ATTR-CYCLE",
                    "kind": "Attribute",
                    "name": "cycleParam",
                    "owner": "PART-A",
                    "properties": {"valueType": "Real", "defaultValue": 1.0},
                },
            ],
        }
        result = export_simulink(model, fmt="json")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["rows"]), 1)
        self.assertTrue(any("循环" in n for n in result["notes"]))

    def test_parameters_accept_single_string_and_dict_items(self):
        model = {
            "package": "Demo",
            "elements": [
                {
                    "id": "ATTR-A",
                    "kind": "Attribute",
                    "name": "paramA",
                    "owner": "Demo",
                    "properties": {"valueType": "Real", "defaultValue": 1.0},
                },
                {
                    "id": "CONSTRAINT-A",
                    "kind": "Constraint",
                    "name": "oneParam",
                    "owner": "Demo",
                    "properties": {"expression": "x > 0", "parameters": "ATTR-A"},
                },
                {
                    "id": "CONSTRAINT-B",
                    "kind": "Constraint",
                    "name": "dictParam",
                    "owner": "Demo",
                    "properties": {
                        "expression": "x > 0",
                        "parameters": [{"id": "ATTR-A"}, {"name": "missingName"}],
                    },
                },
            ],
        }
        result = export_simulink(model, fmt="json", scope="constraints")
        rows = rows_by_id(result)
        self.assertEqual(rows["CONSTRAINT-A"]["parameters"], ["paramA"])
        self.assertEqual(rows["CONSTRAINT-B"]["parameters"], ["paramA", "missingName"])
        self.assertTrue(any("missingName" in n for n in result["notes"]))

    def test_nested_path_uses_owner_chain(self):
        model = fixture_model()
        result = export_simulink(model, fmt="json", scope="attributes")
        rows = rows_by_id(result)
        self.assertEqual(rows["ATTR-NESTED"]["path"], "Demo.Frame")
        self.assertEqual(rows["ATTR-TOP"]["path"], "Demo")


if __name__ == "__main__":
    unittest.main()
