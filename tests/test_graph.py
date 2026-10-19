"""Q2 —— ``tools.graph`` 的 IR→图投影契约（``sysml-graph/v1``）。

钉住四件事：

1. **结构与计数**：golden 34 元素 / 20 关系，4 个固定视图，schema/字段形状；
2. **四个视图的语义**：structure-root 的 owner 树 + typeRef/decomposes、
   ibd-power-chain 的两个 Connection 端点、requirements 的 4 条需求 + 追溯边、
   state-flight-modes 的 5 状态 / 5 迁移（含合成节点 id）；
3. **确定性**：两次 build 逐字节一致、IR 键序打乱后输出不变、elements 顺序无关；
4. **健壮性**：非法输入返回 ``ok=false`` 而不抛异常；CLI ``--check`` / ``--view`` /
   ``--output`` 可跑且退出码正确。

不使用 pytest；只用标准库 ``unittest``（与仓库其余测试一致）。
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _support import GOLDEN_IR, MCP_SERVER, REPO_ROOT, base_model, extended_model, golden_model

from tools.graph import (
    GRAPH_SCHEMA_ID,
    KIND_ORDER,
    RELATION_ORDER,
    VIEW_ORDER,
    build_graph,
    canonical_json,
    content_sha256,
    export_graph,
)

GRAPH_PY = MCP_SERVER / "tools" / "graph.py"

NODE_KEYS = {"id", "kind", "label", "owner", "parent", "attrs"}
EDGE_REQUIRED_KEYS = {"id", "kind", "source", "target", "label"}
EDGE_ALLOWED_KEYS = EDGE_REQUIRED_KEYS | {"rationale"}
VIEW_KEYS = {"viewId", "kind", "scope", "title", "description", "nodes", "edges", "groups"}
VIEW_KIND_BY_ID = {
    "structure-root": "GeneralView",
    "ibd-power-chain": "InterconnectionView",
    "requirements": "RequirementView",
    "state-flight-modes": "StateView",
}


def kind_rank(kind: str) -> int:
    return KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER)


def edge_sort_key(edge: dict) -> tuple:
    return (edge["kind"], edge["source"], edge["target"], edge["id"])


def view_by_id(graph: dict, view_id: str) -> dict:
    for view in graph["views"]:
        if view["viewId"] == view_id:
            return view
    raise AssertionError("视图不存在：%s" % view_id)


def node_by_id(view: dict, node_id: str) -> dict:
    for node in view["nodes"]:
        if node["id"] == node_id:
            return node
    raise AssertionError("节点不存在：%s" % node_id)


def dump(result: dict) -> str:
    """不排序键的序列化：真正检查「输出字节」是否稳定。"""
    return json.dumps(result, ensure_ascii=False, sort_keys=False)


class TestSchemaAndCounts(unittest.TestCase):
    """schema / modelRef / stats 与四视图的基本契约。"""

    @classmethod
    def setUpClass(cls):
        cls.model = golden_model()
        cls.result = build_graph(cls.model)
        cls.graph = cls.result["graph"]

    def test_build_ok_and_schema(self):
        self.assertTrue(self.result["ok"], msg=self.result["errors"])
        self.assertEqual(self.result["errors"], [])
        self.assertEqual(self.graph["schema"], GRAPH_SCHEMA_ID)
        self.assertEqual(GRAPH_SCHEMA_ID, "sysml-graph/v1")

    def test_model_ref_counts_and_hash(self):
        model_ref = self.graph["modelRef"]
        self.assertEqual(model_ref["package"], "CoaxialOctoRotor")
        self.assertEqual(model_ref["elementCount"], 34)
        self.assertEqual(model_ref["relationCount"], 20)
        expected = hashlib.sha256(canonical_json(self.model).encode("utf-8")).hexdigest()
        self.assertEqual(model_ref["contentSha256"], expected)
        self.assertEqual(model_ref["contentSha256"], content_sha256(self.model))
        self.assertRegex(model_ref["contentSha256"], r"^[0-9a-f]{64}$")

    def test_stats_are_pinned(self):
        stats = self.graph["stats"]
        self.assertEqual(stats["viewCount"], 4)
        self.assertEqual(stats["nodeCount"], 56)
        self.assertEqual(stats["edgeCount"], 34)
        self.assertEqual(
            stats["elementsByKind"],
            {
                "PartDefinition": 7,
                "PartUsage": 8,
                "Requirement": 4,
                "ActionDefinition": 2,
                "StateDefinition": 1,
                "Attribute": 9,
                "Constraint": 1,
                "Connection": 2,
            },
        )
        self.assertEqual(
            stats["relationsByType"],
            {"refines": 3, "satisfiedBy": 5, "decomposes": 3, "verifies": 4, "connects": 5},
        )
        self.assertEqual(
            list(stats["elementsByKind"]),
            list(KIND_ORDER),
            msg="elementsByKind 的列序必须固定为 KIND_ORDER（前端/序列化都按它）",
        )
        self.assertEqual(list(stats["relationsByType"]), list(RELATION_ORDER))

    def test_four_views_present_in_fixed_order(self):
        views = self.graph["views"]
        self.assertEqual([view["viewId"] for view in views], list(VIEW_ORDER))
        self.assertEqual(VIEW_ORDER, ("structure-root", "ibd-power-chain", "requirements", "state-flight-modes"))
        for view in views:
            self.assertEqual(set(view), VIEW_KEYS)
            self.assertEqual(view["kind"], VIEW_KIND_BY_ID[view["viewId"]])
            self.assertIsInstance(view["scope"], str)
            self.assertIsInstance(view["title"], str)
            self.assertIsInstance(view["description"], str)
            self.assertIsInstance(view["nodes"], list)
            self.assertIsInstance(view["edges"], list)
            self.assertIsInstance(view["groups"], list)

    def test_node_contract(self):
        for view in self.graph["views"]:
            ids = [node["id"] for node in view["nodes"]]
            self.assertEqual(len(ids), len(set(ids)), msg="%s 内节点 id 重复" % view["viewId"])
            for node in view["nodes"]:
                self.assertEqual(set(node), NODE_KEYS)
                self.assertIsInstance(node["id"], str)
                self.assertIsInstance(node["kind"], str)
                self.assertIsInstance(node["label"], str)
                self.assertTrue(node["label"])
                self.assertTrue(node["owner"] is None or isinstance(node["owner"], str))
                self.assertTrue(node["parent"] is None or isinstance(node["parent"], str))
                self.assertIsInstance(node["attrs"], dict)
                if node["parent"] is not None:
                    self.assertIn(
                        node["parent"],
                        ids,
                        msg="%s 的 parent 必须是本视图内节点" % node["id"],
                    )

    def test_edge_contract(self):
        for view in self.graph["views"]:
            node_ids = {node["id"] for node in view["nodes"]}
            edge_ids = [edge["id"] for edge in view["edges"]]
            self.assertEqual(len(edge_ids), len(set(edge_ids)), msg="%s 内边 id 重复" % view["viewId"])
            for edge in view["edges"]:
                self.assertTrue(EDGE_REQUIRED_KEYS <= set(edge))
                self.assertTrue(set(edge) <= EDGE_ALLOWED_KEYS)
                self.assertIsInstance(edge["label"], str)
                if "rationale" in edge:
                    self.assertIsInstance(edge["rationale"], str)
                    self.assertTrue(edge["rationale"])
                self.assertIn(edge["source"], node_ids, msg="边端点必须在本视图内：%s" % edge["id"])
                self.assertIn(edge["target"], node_ids, msg="边端点必须在本视图内：%s" % edge["id"])

    def test_nodes_sorted_by_kind_order_then_id(self):
        for view in self.graph["views"]:
            expected = sorted(
                view["nodes"], key=lambda node: (kind_rank(node["kind"]), node["id"])
            )
            self.assertEqual(view["nodes"], expected, msg=view["viewId"])

    def test_edges_sorted_by_kind_source_target_id(self):
        for view in self.graph["views"]:
            self.assertEqual(view["edges"], sorted(view["edges"], key=edge_sort_key), msg=view["viewId"])

    def test_groups_cover_every_node_exactly_once(self):
        for view in self.graph["views"]:
            grouped = []
            for group in view["groups"]:
                self.assertEqual(
                    set(group), {"groupId", "label", "kind", "nodeIds", "count"}
                )
                self.assertEqual(group["groupId"], "kind:" + group["kind"])
                self.assertEqual(group["label"], group["kind"])
                self.assertEqual(group["count"], len(group["nodeIds"]))
                self.assertEqual(group["nodeIds"], sorted(group["nodeIds"]))
                grouped.extend(group["nodeIds"])
            self.assertEqual(sorted(grouped), sorted(node["id"] for node in view["nodes"]))
            ranks = [kind_rank(group["kind"]) for group in view["groups"]]
            self.assertEqual(ranks, sorted(ranks), msg="groups 必须按 KIND_ORDER 排")

    def test_result_is_json_serializable(self):
        payload = json.dumps(self.result, ensure_ascii=False, indent=2)
        self.assertIn('"schema": "sysml-graph/v1"', payload)


class TestStructureRoot(unittest.TestCase):
    """General View：owner 层级树 + PartDefinition/PartUsage + typeRef/decomposes。"""

    @classmethod
    def setUpClass(cls):
        cls.model = golden_model()
        cls.view = view_by_id(build_graph(cls.model)["graph"], "structure-root")

    def test_covers_all_elements(self):
        self.assertEqual({node["id"] for node in self.view["nodes"]}, {e["id"] for e in self.model["elements"]})
        self.assertEqual(len(self.view["nodes"]), 34)
        self.assertEqual(self.view["scope"], "CoaxialOctoRotor")

    def test_owner_tree_parent_links(self):
        node = node_by_id(self.view, "PART-USAGE-POWER-CHAIN")
        self.assertEqual(node["owner"], "PART-STRUCT-SYSTEM")
        self.assertEqual(node["parent"], "PART-STRUCT-SYSTEM")
        node = node_by_id(self.view, "PART-USAGE-SYSTEM")
        self.assertEqual(node["owner"], "CoaxialOctoRotor")
        self.assertIsNone(node["parent"], msg="package 级元素在图内没有父元素节点")
        node = node_by_id(self.view, "PART-BATTERY-PACK")
        self.assertEqual(node["kind"], "PartDefinition")
        self.assertEqual(node["label"], "BatteryPack")

    def test_typeref_edges(self):
        edges = [edge for edge in self.view["edges"] if edge["kind"] == "typeRef"]
        self.assertEqual(len(edges), 8, msg="8 个 PartUsage 各有一条 typeRef 边")
        battery = [edge for edge in edges if edge["source"] == "PART-USAGE-BATTERY"]
        self.assertEqual(len(battery), 1)
        self.assertEqual(battery[0]["target"], "PART-BATTERY-PACK")
        self.assertEqual(battery[0]["label"], "BatteryPack")
        esc = [edge for edge in edges if edge["source"] == "PART-USAGE-ESC"]
        self.assertEqual(esc[0]["target"], "PART-ESC")

    def test_decomposes_edges(self):
        edges = [edge for edge in self.view["edges"] if edge["kind"] == "decomposes"]
        pairs = sorted((edge["source"], edge["target"]) for edge in edges)
        self.assertEqual(
            pairs,
            [
                ("ACT-ONLINE-OPTIMIZATION", "ACT-SIM-ENDURANCE"),
                ("PART-STRUCT-SYSTEM", "PART-POWER-CHAIN"),
                ("REQ-MISSION-ENDURANCE", "REQ-CRUISE-ENDURANCE"),
            ],
        )
        for edge in edges:
            if edge["source"] == "PART-STRUCT-SYSTEM":
                self.assertEqual(edge["rationale"], "整机在结构上分解为功率链等子系统")

    def test_display_attrs_only_keep_needed_fields(self):
        esc = node_by_id(self.view, "PART-USAGE-ESC")
        self.assertEqual(esc["attrs"]["typeRef"], "PART-ESC")
        self.assertEqual(esc["attrs"]["typeName"], "ElectronicSpeedController")
        self.assertEqual(esc["attrs"]["quantity"], 8)
        capacity = node_by_id(self.view, "ATTR-BATTERY-CAPACITY")
        self.assertEqual(capacity["attrs"]["defaultValue"], 1200.0)
        self.assertEqual(capacity["attrs"]["unit"], "Wh")
        req = node_by_id(self.view, "REQ-CRUISE-ENDURANCE")
        self.assertEqual(req["attrs"]["thresholds"], {"minEnduranceHours": 4.0})
        self.assertIn("text", req["attrs"])
        constraint = node_by_id(self.view, "CONSTRAINT-ENDURANCE-BUDGET")
        self.assertIn("expression", constraint["attrs"])
        self.assertEqual(len(constraint["attrs"]["parameters"]), 4)


class TestIbdPowerChain(unittest.TestCase):
    """Interconnection View：Connection 端点 / flowKind / quantity。"""

    @classmethod
    def setUpClass(cls):
        cls.model = golden_model()
        cls.view = view_by_id(build_graph(cls.model)["graph"], "ibd-power-chain")

    def test_scope_and_nodes(self):
        self.assertEqual(self.view["scope"], "PART-POWER-CHAIN")
        ids = {node["id"] for node in self.view["nodes"]}
        self.assertEqual(
            ids,
            {
                "PART-POWER-CHAIN",
                "PART-USAGE-BATTERY",
                "PART-USAGE-ESC",
                "PART-USAGE-MOTOR-LOWER",
                "PART-USAGE-MOTOR-UPPER",
                "PART-USAGE-PROP-LOWER",
                "PART-USAGE-PROP-UPPER",
            },
        )
        for usage_id in ids - {"PART-POWER-CHAIN"}:
            self.assertEqual(node_by_id(self.view, usage_id)["parent"], "PART-POWER-CHAIN")
        self.assertIsNone(node_by_id(self.view, "PART-POWER-CHAIN")["parent"])

    def test_two_connections_with_correct_endpoints(self):
        connections = [edge for edge in self.view["edges"] if edge["kind"] == "connection"]
        self.assertEqual(len(connections), 2)
        pairs = {
            (edge["source"], edge["target"]): edge["label"] for edge in connections
        }
        self.assertEqual(
            pairs,
            {
                ("PART-USAGE-BATTERY", "PART-USAGE-ESC"): "electrical",
                ("PART-USAGE-MOTOR-UPPER", "PART-USAGE-PROP-UPPER"): "mechanical",
            },
        )
        for edge in connections:
            self.assertIn(edge["rationale"], {
                "电池直流母线馈入八路电调。",
                "上桨电机把轴功率传给上桨。",
            })

    def test_connects_trace_edges_supplement_without_duplicating(self):
        pair_counts = {}
        for edge in self.view["edges"]:
            pair_counts[(edge["source"], edge["target"])] = pair_counts.get(
                (edge["source"], edge["target"]), 0
            ) + 1
        self.assertEqual(pair_counts[("PART-USAGE-BATTERY", "PART-USAGE-ESC")], 1)
        self.assertEqual(pair_counts[("PART-USAGE-MOTOR-UPPER", "PART-USAGE-PROP-UPPER")], 1)
        connects = [edge for edge in self.view["edges"] if edge["kind"] == "connects"]
        self.assertEqual(
            {(edge["source"], edge["target"]) for edge in connects},
            {
                ("PART-USAGE-ESC", "PART-USAGE-MOTOR-UPPER"),
                ("PART-USAGE-ESC", "PART-USAGE-MOTOR-LOWER"),
                ("PART-USAGE-MOTOR-LOWER", "PART-USAGE-PROP-LOWER"),
            },
        )
        for edge in connects:
            self.assertEqual(edge["label"], "connects")
            self.assertTrue(edge["rationale"])

    def test_quantity_attrs(self):
        expected = {
            "PART-USAGE-BATTERY": 1,
            "PART-USAGE-ESC": 8,
            "PART-USAGE-MOTOR-UPPER": 4,
            "PART-USAGE-MOTOR-LOWER": 4,
            "PART-USAGE-PROP-UPPER": 4,
            "PART-USAGE-PROP-LOWER": 4,
        }
        for node_id, quantity in expected.items():
            self.assertEqual(node_by_id(self.view, node_id)["attrs"]["quantity"], quantity)


class TestRequirements(unittest.TestCase):
    """Requirement View：4 条需求 + refines/decomposes/satisfiedBy/verifies。"""

    @classmethod
    def setUpClass(cls):
        cls.model = golden_model()
        cls.view = view_by_id(build_graph(cls.model)["graph"], "requirements")

    def test_four_requirements(self):
        requirements = [node for node in self.view["nodes"] if node["kind"] == "Requirement"]
        self.assertEqual(len(requirements), 4)
        self.assertEqual(
            {node["id"] for node in requirements},
            {
                "REQ-CRUISE-ENDURANCE",
                "REQ-MISSION-ENDURANCE",
                "REQ-POWER-BUDGET",
                "REQ-ROTOR-SPEED-RATIO",
            },
        )

    def test_trace_edges_by_type(self):
        counts = {}
        for edge in self.view["edges"]:
            counts[edge["kind"]] = counts.get(edge["kind"], 0) + 1
        self.assertEqual(
            counts,
            {"decomposes": 1, "refines": 3, "satisfiedBy": 5, "verifies": 4},
        )
        self.assertEqual(len(self.view["edges"]), 13)
        self.assertNotIn("connects", counts, msg="需求视图不展示 connects 追溯边")

    def test_key_trace_edges(self):
        edges = {(edge["kind"], edge["source"], edge["target"]): edge for edge in self.view["edges"]}
        decomposes = edges[("decomposes", "REQ-MISSION-ENDURANCE", "REQ-CRUISE-ENDURANCE")]
        self.assertEqual(decomposes["label"], "decomposes")
        self.assertEqual(decomposes["rationale"], "任务级续航分解为巡航段的续航需求")
        self.assertIn(("satisfiedBy", "REQ-CRUISE-ENDURANCE", "PART-BATTERY-PACK"), edges)
        self.assertIn(("verifies", "ACT-SIM-ENDURANCE", "REQ-CRUISE-ENDURANCE"), edges)
        self.assertIn(("refines", "REQ-ROTOR-SPEED-RATIO", "REQ-CRUISE-ENDURANCE"), edges)

    def test_external_endpoints_are_included_as_nodes(self):
        ids = {node["id"] for node in self.view["nodes"]}
        for external in (
            "PART-POWER-CHAIN",
            "PART-BATTERY-PACK",
            "PART-USAGE-SYSTEM",
            "ACT-ONLINE-OPTIMIZATION",
            "ACT-SIM-ENDURANCE",
        ):
            self.assertIn(external, ids)


class TestStateFlightModes(unittest.TestCase):
    """State View：5 状态 / 5 迁移，节点 id 合成为 ``STATE-...::<state>``。"""

    @classmethod
    def setUpClass(cls):
        cls.model = golden_model()
        cls.view = view_by_id(build_graph(cls.model)["graph"], "state-flight-modes")

    def test_scope_and_container(self):
        self.assertEqual(self.view["scope"], "STATE-FLIGHT-MODES")
        container = node_by_id(self.view, "STATE-FLIGHT-MODES")
        self.assertEqual(container["kind"], "StateDefinition")
        self.assertIn("飞行模式状态机", container["attrs"]["description"])

    def test_five_states_with_synthesized_ids(self):
        states = [node for node in self.view["nodes"] if node["kind"] == "State"]
        self.assertEqual(len(states), 5)
        self.assertEqual(
            {node["id"] for node in states},
            {"STATE-FLIGHT-MODES::%s" % name for name in
             ("Takeoff", "Cruise", "ReturnToHome", "Fault", "Landed")},
        )
        for node in states:
            self.assertEqual(node["owner"], "STATE-FLIGHT-MODES")
            self.assertEqual(node["parent"], "STATE-FLIGHT-MODES")

    def test_initial_state_is_marked_by_attrs(self):
        initial = [
            node
            for node in self.view["nodes"]
            if node["kind"] == "State" and node["attrs"].get("initial")
        ]
        self.assertEqual([node["id"] for node in initial], ["STATE-FLIGHT-MODES::Takeoff"])

    def test_five_transitions_match_ir(self):
        transitions = [edge for edge in self.view["edges"] if edge["kind"] == "transition"]
        self.assertEqual(len(transitions), 5)
        pairs = {(edge["source"].split("::")[-1], edge["target"].split("::")[-1]) for edge in transitions}
        self.assertEqual(
            pairs,
            {("Takeoff", "Cruise"), ("Cruise", "ReturnToHome"), ("Cruise", "Fault"),
             ("ReturnToHome", "Landed"), ("Fault", "Landed")},
        )
        by_pair = {(edge["source"], edge["target"]): edge for edge in transitions}
        self.assertEqual(by_pair[("STATE-FLIGHT-MODES::Takeoff", "STATE-FLIGHT-MODES::Cruise")]["label"], "")
        self.assertEqual(
            by_pair[("STATE-FLIGHT-MODES::Cruise", "STATE-FLIGHT-MODES::ReturnToHome")]["label"],
            "返航指令或任务段剩余时间不足",
        )
        fault = by_pair[("STATE-FLIGHT-MODES::Cruise", "STATE-FLIGHT-MODES::Fault")]["label"]
        self.assertIn("转速比越界或功率遥测持续异常", fault)
        self.assertIn("if (x8System.speedRatioEta <= 0.75)", fault)

    def test_transition_edge_ids_are_stable_and_unique(self):
        transitions = [edge for edge in self.view["edges"] if edge["kind"] == "transition"]
        ids = [edge["id"] for edge in transitions]
        self.assertEqual(len(ids), len(set(ids)))
        for edge in transitions:
            self.assertTrue(edge["id"].startswith("transition:"), msg=edge["id"])


class TestDeterminism(unittest.TestCase):
    """同一 IR 必得逐字节一致的图；与 JSON 键序 / elements 顺序无关。"""

    @classmethod
    def setUpClass(cls):
        cls.model = golden_model()

    def test_two_builds_are_byte_identical(self):
        first = build_graph(copy.deepcopy(self.model))
        second = build_graph(copy.deepcopy(self.model))
        self.assertEqual(dump(first), dump(second))
        self.assertEqual(
            first["graph"]["modelRef"]["contentSha256"],
            second["graph"]["modelRef"]["contentSha256"],
        )

    def test_json_key_order_does_not_matter(self):
        def shuffle_keys(value):
            if isinstance(value, dict):
                return {key: shuffle_keys(value[key]) for key in reversed(list(value))}
            if isinstance(value, list):
                return [shuffle_keys(item) for item in value]
            return value

        original = build_graph(self.model)
        shuffled = build_graph(shuffle_keys(self.model))
        self.assertEqual(dump(original), dump(shuffled))

    def test_elements_array_order_does_not_change_views(self):
        first = build_graph(self.model)
        model = copy.deepcopy(self.model)
        model["elements"] = list(reversed(model["elements"]))
        second = build_graph(model)
        self.assertEqual(
            dump(first["graph"]["views"]),
            dump(second["graph"]["views"]),
            msg="视图投影不允许依赖 elements 数组顺序",
        )
        self.assertEqual(first["graph"]["stats"], second["graph"]["stats"])

    def test_content_sha_is_canonical(self):
        reordered = {key: self.model[key] for key in reversed(list(self.model))}
        self.assertEqual(canonical_json(self.model), canonical_json(reordered))
        self.assertEqual(content_sha256(self.model), content_sha256(reordered))

    def test_does_not_mutate_input_model(self):
        model = golden_model()
        snapshot = copy.deepcopy(model)
        build_graph(model)
        self.assertEqual(model, snapshot)

    def test_export_graph_alias(self):
        self.assertEqual(
            dump(export_graph(self.model)),
            dump(build_graph(self.model)),
        )


class TestInvalidInput(unittest.TestCase):
    """非法输入：不抛异常，返回 ``ok=false + errors``（graph 为 null）。"""

    def assert_failed(self, model):
        try:
            result = build_graph(model)
        except Exception as exc:  # pragma: no cover - 失败信息本身就是要展示的断言
            self.fail("build_graph 不应抛异常，实际抛出 %r" % (exc,))
        self.assertFalse(result["ok"])
        self.assertIsNone(result["graph"])
        self.assertGreaterEqual(len(result["errors"]), 1)
        return result

    def test_non_json_string(self):
        result = self.assert_failed("这不是 JSON")
        self.assertEqual(result["errors"][0]["code"], "E-GRAPH-INPUT")

    def test_non_object_root(self):
        result = self.assert_failed([{"schema": "sysml-ir/v1"}])
        self.assertTrue(result["errors"])

    def test_wrong_schema_version(self):
        model = golden_model()
        model["schema"] = "sysml-ir/v2"
        result = self.assert_failed(model)
        self.assertIn("E-SCHEMA-VERSION", [error["code"] for error in result["errors"]])

    def test_empty_elements(self):
        result = self.assert_failed({"schema": "sysml-ir/v1", "package": "Demo", "elements": []})
        self.assertIn("E-ELEMENTS-EMPTY", [error["code"] for error in result["errors"]])

    def test_dangling_relation_target(self):
        model = copy.deepcopy(golden_model())
        for element in model["elements"]:
            if element["id"] == "REQ-CRUISE-ENDURANCE":
                element["relations"][0]["target"] = "REQ-NOT-EXIST"
                break
        result = self.assert_failed(model)
        self.assertIn("E-REL-TARGET-DANGLING", [error["code"] for error in result["errors"]])

    def test_none_input(self):
        self.assert_failed(None)

    def test_validation_codes_are_passed_through(self):
        """错误结构沿用 validate_model_json（code/element/message/pointer），前端可复用。"""
        result = self.assert_failed({"schema": "sysml-ir/v1", "package": "Demo", "elements": [{"id": "X"}]})
        for error in result["errors"]:
            self.assertIn("code", error)
            self.assertIn("message", error)


class TestCommandLine(unittest.TestCase):
    """CLI：``--check`` / 默认投影 / ``--view`` / ``--output`` 与退出码。"""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory(prefix="sysml-graph-")

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(GRAPH_PY), *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )

    def test_check_golden(self):
        completed = self.run_cli("--input", str(GOLDEN_IR), "--check")
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["errors"], [])
        self.assertIn("schemaLayer", payload)

    def test_check_rejects_bad_model_with_exit_1(self):
        bad = Path(self.tmpdir.name) / "bad.ir.json"
        bad.write_text('{"schema": "bogus"}', encoding="utf-8")
        completed = self.run_cli("--input", str(bad), "--check")
        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["errors"])

    def test_check_rejects_non_json_file(self):
        bad = Path(self.tmpdir.name) / "not-json.ir.json"
        bad.write_text("not json at all", encoding="utf-8")
        completed = self.run_cli("--input", str(bad), "--check")
        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"][0]["code"], "E-GRAPH-INPUT")

    def test_build_to_stdout(self):
        completed = self.run_cli("--input", str(GOLDEN_IR))
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["graph"]["schema"], GRAPH_SCHEMA_ID)
        self.assertEqual([view["viewId"] for view in payload["graph"]["views"]], list(VIEW_ORDER))
        self.assertEqual(payload["graph"]["modelRef"]["elementCount"], 34)

    def test_stdout_is_deterministic_between_runs(self):
        first = self.run_cli("--input", str(GOLDEN_IR))
        second = self.run_cli("--input", str(GOLDEN_IR))
        self.assertEqual(first.stdout, second.stdout)

    def test_view_filter(self):
        completed = self.run_cli("--input", str(GOLDEN_IR), "--view", "requirements")
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["graph"]["views"]), 1)
        self.assertEqual(payload["graph"]["views"][0]["viewId"], "requirements")
        self.assertEqual(payload["graph"]["stats"]["viewCount"], 1)

    def test_unknown_view_is_rejected(self):
        completed = self.run_cli("--input", str(GOLDEN_IR), "--view", "no-such-view")
        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"][0]["code"], "E-GRAPH-VIEW-UNKNOWN")

    def test_output_file_matches_stdout_payload(self):
        output = Path(self.tmpdir.name) / "graph.json"
        completed = self.run_cli("--input", str(GOLDEN_IR), "--output", str(output))
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        written = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(written["ok"])
        self.assertEqual(written["graph"], build_graph(golden_model())["graph"])
        summary = json.loads(completed.stdout)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["viewCount"], 4)

    def test_py_compile(self):
        import py_compile

        cfile = Path(self.tmpdir.name) / "graph.pyc"
        py_compile.compile(str(GRAPH_PY), cfile=str(cfile), doraise=True)


class TestOtherModelsStillProject(unittest.TestCase):
    """非标杆模型也应有 4 个视图（通用性冒烟，不要求视图内容非空）。"""

    def test_base_model(self):
        graph = build_graph(base_model())["graph"]
        self.assertEqual([view["viewId"] for view in graph["views"]], list(VIEW_ORDER))
        state_view = view_by_id(graph, "state-flight-modes")
        self.assertEqual(state_view["scope"], "STATE-A")
        self.assertEqual(
            {node["id"] for node in state_view["nodes"]},
            {"STATE-A", "STATE-A::Idle", "STATE-A::Running"},
        )

    def test_extended_model_ibd_falls_back_to_connection_owner(self):
        graph = build_graph(extended_model())["graph"]
        view = view_by_id(graph, "ibd-power-chain")
        self.assertEqual(view["scope"], "Demo", msg="没有 PART-POWER-CHAIN 时取 Connection 的 owner")
        connections = [edge for edge in view["edges"] if edge["kind"] == "connection"]
        self.assertEqual(len(connections), 1)
        self.assertEqual(connections[0]["label"], "electrical")

    def test_model_without_state_definition_has_empty_state_view(self):
        model = base_model()
        model["elements"] = [
            element for element in model["elements"] if element["kind"] != "StateDefinition"
        ]
        graph = build_graph(model)["graph"]
        view = view_by_id(graph, "state-flight-modes")
        self.assertEqual(view["nodes"], [])
        self.assertEqual(view["edges"], [])
        self.assertEqual(view["groups"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
