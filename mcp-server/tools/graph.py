"""``build_graph`` / ``export_graph`` —— IR JSON → 图投影（``sysml-graph/v1``）。

定位（Q2「图形化侧边栏」的数据契约层）：**只做投影，不画图、不做布局**。
把 IR 投影成前端可直接消费的「节点 + 边 + 分组」结构；视图顺序、节点顺序、边顺序
全部固定，同一份 IR 必得逐字节一致的图 JSON。IR 仍是唯一事实源，图不落盘、不反写。

核心 API::

    build_graph(model) -> {"ok": bool, "graph": {...} | None, "errors": [...], "warnings": [...]}

- 成功：``ok=true``，``graph.schema == "sysml-graph/v1"``；
- 失败（非法 IR / 非 JSON / 顶层不是对象）：``ok=false``、``graph=null``，
  ``errors`` 沿用 ``validate_model_json`` 的错误码与结构，**不抛异常**；
- ``export_graph`` 是 ``build_graph`` 的同义别名（与任务/方案里的叫法对齐）。

四个视图（``VIEW_ORDER``，顺序固定）::

    structure-root       GeneralView         owner 层级 + PartDefinition/PartUsage + typeRef/decomposes
    ibd-power-chain      InterconnectionView Connection(sourceRef/targetRef/flowKind) + PartUsage.quantity
    requirements         RequirementView     Requirement + refines/decomposes/satisfiedBy/verifies
    state-flight-modes   StateView           StateDefinition.states/transitions（合成 ``<id>::<state>`` 节点）

确定性规则（与 ``schema/渲染约定.md`` §1.2 同源）：

1. ``views`` 按 ``VIEW_ORDER``；
2. ``nodes`` 按 ``KIND_ORDER``（8 种 IR kind，合成 ``State`` 置末）再按 ``id`` 升序；
3. ``edges`` 按 ``(kind, source, target, id)`` 升序；边 id 由本模块合成且稳定；
4. ``modelRef.contentSha256`` = IR 规范化 JSON（``sort_keys=True``、
   ``separators=(",", ":")``、``ensure_ascii=False``）的 sha256；
5. 所有集合都不依赖 JSON 对象键序 / ``elements`` 数组顺序。

CLI::

    python mcp-server/tools/graph.py --input <ir.json> [--output <json>] [--view <id>] [--check]

``--check`` 只校验输入并输出 ``{ok, errors, warnings, schemaLayer}``；
``--output`` 省略或为 ``-`` 时写标准输出，否则写文件并在 stdout 打一行摘要。

纯标准库；除 ``--output`` 指定文件外不做任何写入；不修改传入的 ``model``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # 包内导入：``from tools.graph import build_graph``
    from .validator import KINDS, RELATION_TYPES, validate_model_json
except ImportError:  # 直接当脚本运行：``python mcp-server/tools/graph.py ...``
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.validator import KINDS, RELATION_TYPES, validate_model_json

#: 本工具产出的图 JSON schema 版本
GRAPH_SCHEMA_ID = "sysml-graph/v1"

#: 输入 IR 的 schema 版本（仅用于文档/说明，校验由 validator 负责）
IR_SCHEMA_ID = "sysml-ir/v1"

#: 节点排序用的 kind 顺序：直接复用 IR 的 KIND_ORDER（见 ``渲染约定.md`` §1.2）
KIND_ORDER: Tuple[str, ...] = tuple(KINDS)

#: 关系 type 顺序（只用于 stats 的稳定列序）
RELATION_ORDER: Tuple[str, ...] = tuple(RELATION_TYPES)

#: 合成的状态节点 kind（不是 IR kind，排序时置于所有 IR kind 之后）
STATE_KIND = "State"

#: 节点排序的完整 kind 顺序：8 种 IR kind + 合成 State
NODE_KIND_ORDER: Tuple[str, ...] = KIND_ORDER + (STATE_KIND,)

#: 视图固定顺序（前端/测试都按这个顺序消费）
VIEW_ORDER: Tuple[str, ...] = (
    "structure-root",
    "ibd-power-chain",
    "requirements",
    "state-flight-modes",
)

#: 每个视图对应的 SysML v2 视图种类（v1 的 BDD/IBD 在 v2 里是 View，不是图名）
VIEW_KINDS: Dict[str, str] = {
    "structure-root": "GeneralView",
    "ibd-power-chain": "InterconnectionView",
    "requirements": "RequirementView",
    "state-flight-modes": "StateView",
}

#: 互联视图的优先 scope（标杆案例里的功率链）；不存在时按下面的规则自动选
IBD_PRIMARY_SCOPE = "PART-POWER-CHAIN"

#: 状态机视图的优先 scope（标杆案例里的飞行模式状态机）；不存在时选 id 最小的 StateDefinition
STATE_PRIMARY_SCOPE = "STATE-FLIGHT-MODES"

#: 需求视图里展示的追溯关系类型（5 种里不含 connects）
REQUIREMENT_TRACE_TYPES: Tuple[str, ...] = ("refines", "decomposes", "satisfiedBy", "verifies")

#: 结构总览里展示的追溯关系类型
STRUCTURE_TRACE_TYPES: Tuple[str, ...] = ("decomposes",)

#: Requirement 里属于「保留字符串字段」的名字；其余 props 字段一律视为阈值（与 validator 一致）
REQUIREMENT_STRING_FIELDS = frozenset(
    (
        "text",
        "acceptanceCriteria",
        "verifyMethod",
        "rationale",
        "source",
        "priority",
        "description",
    )
)

__all__ = [
    "GRAPH_SCHEMA_ID",
    "IR_SCHEMA_ID",
    "KIND_ORDER",
    "RELATION_ORDER",
    "NODE_KIND_ORDER",
    "VIEW_ORDER",
    "VIEW_KINDS",
    "build_graph",
    "export_graph",
    "canonical_json",
    "content_sha256",
]


# --------------------------------------------------------------------------------------
# 公开入口
# --------------------------------------------------------------------------------------


def build_graph(model: Any) -> Dict[str, Any]:
    """把 IR JSON 投影成 ``sysml-graph/v1`` 图数据（纯函数、确定性）。

    :param model: IR JSON（dict，或可被 ``json.loads`` 的 str/bytes）
    :return: ``{"ok": bool, "graph": dict | None, "errors": [...], "warnings": [...]}``。
        非法输入不抛异常：``ok=false``，``graph=null``，原因写进 ``errors``。
    """
    try:
        return _build_graph(model)
    except Exception as exc:  # noqa: BLE001 - 输入来自 LLM/外部文件，必须宽进严出
        return _failure(
            [
                _error(
                    "E-GRAPH-INTERNAL",
                    "图投影内部错误（已捕获，未抛给调用方）：%s: %s。" % (type(exc).__name__, exc),
                )
            ]
        )


def export_graph(model: Any) -> Dict[str, Any]:
    """``build_graph`` 的同义别名（方案/任务里把该工具叫 ``export_graph``）。"""
    return build_graph(model)


def canonical_json(model: Any) -> str:
    """IR 的规范化 JSON：``sort_keys=True`` + ``separators=(",", ":")`` + 不转义中文。"""
    return json.dumps(model, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_sha256(model: Any) -> str:
    """对 IR 规范化 JSON 取 sha256（同一 IR 必得同一哈希，与对象键序无关）。"""
    return hashlib.sha256(canonical_json(model).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------------------


def _build_graph(model: Any) -> Dict[str, Any]:
    model, parse_error = _coerce_model(model)
    if parse_error is not None:
        return _failure([_error("E-GRAPH-INPUT", parse_error)])

    validation = validate_model_json(model)
    if not validation.get("ok"):
        errors = list(validation.get("errors") or [])
        if not errors:
            errors = [_error("E-GRAPH-MODEL-INVALID", "模型校验未通过（validate_model_json 返回 ok=false）。")]
        return _failure(errors, validation.get("warnings") or [])

    if not isinstance(model, dict):  # 双保险：validate 已挡非对象顶层
        return _failure([_error("E-GRAPH-ROOT", "IR 顶层必须是 JSON 对象。")])

    elements, by_id, package = _index(model)
    views = [
        _structure_view(package, elements, by_id),
        _ibd_view(package, elements, by_id),
        _requirements_view(package, elements, by_id),
        _state_view(elements, by_id),
    ]
    graph = {
        "schema": GRAPH_SCHEMA_ID,
        "modelRef": {
            "package": package,
            "elementCount": len(elements),
            "relationCount": _relation_count(elements),
            "contentSha256": content_sha256(model),
        },
        "views": views,
        "stats": _stats(elements, views),
    }
    return {"ok": True, "graph": graph, "errors": [], "warnings": list(validation.get("warnings") or [])}


# --------------------------------------------------------------------------------------
# 视图 1/4：structure-root（GeneralView）
# --------------------------------------------------------------------------------------


def _structure_view(
    package: str,
    elements: List[Dict[str, Any]],
    by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """结构总览：全部元素的 owner 层级树 + ``typeRef`` / ``decomposes`` 边。"""
    node_ids = set(by_id)
    nodes = [_make_node(element, by_id, node_ids) for element in elements]

    edges: List[Dict[str, Any]] = []
    for element in sorted(elements, key=lambda item: item["id"]):
        element_id = element["id"]
        type_ref = _props(element).get("typeRef")
        if isinstance(type_ref, str) and type_ref in by_id:
            target_name = by_id[type_ref].get("name")
            label = target_name if isinstance(target_name, str) and target_name else type_ref
            edges.append(_make_edge("typeRef", element_id, type_ref, label))
        for relation in _relations(element):
            if relation.get("type") != "decomposes":
                continue
            target = relation.get("target")
            if isinstance(target, str) and target in by_id:
                edges.append(
                    _make_edge("decomposes", element_id, target, "decomposes", relation.get("rationale"))
                )

    return _view(
        "structure-root",
        package,
        "结构总览：%s" % (package or "（无 package）"),
        "General View：owner 层级树 + PartDefinition/PartUsage + typeRef/decomposes 边；"
        "覆盖模型内全部元素，供结构树与下钻使用。",
        nodes,
        edges,
    )


# --------------------------------------------------------------------------------------
# 视图 2/4：ibd-power-chain（InterconnectionView）
# --------------------------------------------------------------------------------------


def _ibd_view(
    package: str,
    elements: List[Dict[str, Any]],
    by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """互联视图：功率链部件的连接关系。

    scope 选取（确定性，优先造好的案例，其次通用规则）：

    1. 存在 ``PART-POWER-CHAIN``（PartDefinition）就用它；
    2. 否则取 id 最小的一条 ``Connection`` 的 owner（owner 是元素则取该元素的子树，
       是 package 名则退化为「全部 PartUsage」）；
    3. 没有 Connection 时，取直接/间接拥有最多 PartUsage 的 PartDefinition（并列取 id 最小）。

    节点 = scope 元素（若有）+ 其子树内的全部 PartUsage；边 = 该范围两端的
    ``Connection``（kind=``connection``，label=flowKind），再用 ``connects`` 追溯边补全，
    同一 ``(source, target)`` 已被正式 Connection 覆盖的不重复出边。
    """
    scope_text, scope_element = _select_ibd_scope(package, elements, by_id)

    node_ids = set()
    if scope_element is not None:
        node_ids.add(scope_element["id"])
        for element in elements:
            if element.get("kind") == "PartUsage" and _owner_chain_contains(
                element, scope_element["id"], by_id
            ):
                node_ids.add(element["id"])
    else:
        node_ids = {element["id"] for element in elements if element.get("kind") == "PartUsage"}

    nodes = [_make_node(by_id[element_id], by_id, node_ids) for element_id in sorted(node_ids)]

    edges: List[Dict[str, Any]] = []
    covered: set = set()
    for connection in sorted(
        (item for item in elements if item.get("kind") == "Connection"),
        key=lambda item: item["id"],
    ):
        props = _props(connection)
        source = props.get("sourceRef")
        target = props.get("targetRef")
        if not (isinstance(source, str) and isinstance(target, str)):
            continue
        if source not in node_ids or target not in node_ids:
            continue
        flow_kind = props.get("flowKind")
        label = flow_kind if isinstance(flow_kind, str) and flow_kind else "connection"
        edges.append(
            _make_edge("connection", source, target, label, props.get("description"))
        )
        covered.add((source, target))

    for element in sorted(elements, key=lambda item: item["id"]):
        if element["id"] not in node_ids:
            continue
        for relation in _relations(element):
            if relation.get("type") != "connects":
                continue
            target = relation.get("target")
            if not (isinstance(target, str) and target in node_ids):
                continue
            if (element["id"], target) in covered:
                continue
            edges.append(
                _make_edge("connects", element["id"], target, "connects", relation.get("rationale"))
            )

    return _view(
        "ibd-power-chain",
        scope_text,
        "互联视图：%s" % (scope_text or "（未指定 scope）"),
        "Interconnection View：Connection 的 sourceRef→targetRef 为边、flowKind 为边标签，"
        "PartUsage 的 quantity 落在节点 attrs；同一 (source, target) 的 connects 追溯边作为补充并去重。",
        nodes,
        edges,
    )


def _select_ibd_scope(
    package: str,
    elements: List[Dict[str, Any]],
    by_id: Dict[str, Dict[str, Any]],
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """选出互联视图的 scope；返回 ``(scope 文本, scope 元素或 None)``。"""
    primary = by_id.get(IBD_PRIMARY_SCOPE)
    if isinstance(primary, dict) and primary.get("kind") == "PartDefinition":
        return IBD_PRIMARY_SCOPE, primary

    connections = sorted(
        (item for item in elements if item.get("kind") == "Connection"),
        key=lambda item: item["id"],
    )
    for connection in connections:
        owner = connection.get("owner")
        if not isinstance(owner, str) or not owner:
            continue
        if owner in by_id:
            return owner, by_id[owner]
        return owner, None  # owner 是 package 名：退化为「全部 PartUsage」

    best: Optional[Dict[str, Any]] = None
    best_count = 0
    for element in sorted(elements, key=lambda item: item["id"]):
        if element.get("kind") != "PartDefinition":
            continue
        count = sum(
            1
            for usage in elements
            if usage.get("kind") == "PartUsage"
            and _owner_chain_contains(usage, element["id"], by_id)
        )
        if count > best_count:
            best, best_count = element, count
    if best is not None:
        return best["id"], best
    return package, None


# --------------------------------------------------------------------------------------
# 视图 3/4：requirements（RequirementView）
# --------------------------------------------------------------------------------------


def _requirements_view(
    package: str,
    elements: List[Dict[str, Any]],
    by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """需求追溯视图：需求 + 与之相关的 refines/decomposes/satisfiedBy/verifies 关系。

    关系另一端（如被满足的结构、执行验证的动作）不是 Requirement 时，作为**外部节点**
    一并并入视图——否则 ``satisfiedBy`` / ``verifies`` 这些最关键的追溯边就画不出来。
    """
    requirement_ids = {
        element["id"] for element in elements if element.get("kind") == "Requirement"
    }
    node_ids = set(requirement_ids)

    edges: List[Dict[str, Any]] = []
    for element in sorted(elements, key=lambda item: item["id"]):
        source = element["id"]
        for relation in _relations(element):
            relation_type = relation.get("type")
            if relation_type not in REQUIREMENT_TRACE_TYPES:
                continue
            target = relation.get("target")
            if not (isinstance(target, str) and target in by_id):
                continue
            if source not in requirement_ids and target not in requirement_ids:
                continue
            node_ids.add(source)
            node_ids.add(target)
            edges.append(
                _make_edge(relation_type, source, target, relation_type, relation.get("rationale"))
            )

    nodes = [_make_node(by_id[element_id], by_id, node_ids) for element_id in sorted(node_ids)]

    return _view(
        "requirements",
        package,
        "需求追溯视图：%s" % (package or "（无 package）"),
        "Requirement View：Requirement 及其 refines/decomposes/satisfiedBy/verifies 关系；"
        "关系另一端不在需求集合内时作为外部节点并入（attrs 不含额外推断）。",
        nodes,
        edges,
    )


# --------------------------------------------------------------------------------------
# 视图 4/4：state-flight-modes（StateView）
# --------------------------------------------------------------------------------------


def _state_view(
    elements: List[Dict[str, Any]],
    by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """状态机视图：一个 StateDefinition 的 states/transitions。

    优先 ``STATE-FLIGHT-MODES``（标杆案例），否则取 id 最小的 StateDefinition；
    合成状态节点 id 为 ``<StateDefinition id>::<state>``（与方案里的 ``STATE-...::<state>``
    一致）。初始态用 ``attrs.initial=true`` 标注，不额外造边。
    """
    definitions = sorted(
        (item for item in elements if item.get("kind") == "StateDefinition"),
        key=lambda item: item["id"],
    )
    primary = by_id.get(STATE_PRIMARY_SCOPE)
    if not (isinstance(primary, dict) and primary.get("kind") == "StateDefinition"):
        primary = definitions[0] if definitions else None

    if primary is None:
        return _view(
            "state-flight-modes",
            "",
            "状态机视图",
            "State Transition View：模型内没有 StateDefinition，本视图为空。",
            [],
            [],
        )

    definition_id = primary["id"]
    props = _props(primary)
    raw_states = props.get("states")
    states = [
        state for state in (raw_states if isinstance(raw_states, list) else []) if isinstance(state, str)
    ]
    initial = props.get("initial") if isinstance(props.get("initial"), str) else None

    state_ids = {"%s::%s" % (definition_id, state) for state in states}
    node_ids = {definition_id} | state_ids
    nodes: List[Dict[str, Any]] = [_make_node(primary, by_id, node_ids)]
    for state in states:
        attrs: Dict[str, Any] = {}
        if initial == state:
            attrs["initial"] = True
        nodes.append(
            {
                "id": "%s::%s" % (definition_id, state),
                "kind": STATE_KIND,
                "label": state,
                "owner": definition_id,
                "parent": definition_id,
                "attrs": attrs,
            }
        )

    edges: List[Dict[str, Any]] = []
    raw_transitions = props.get("transitions")
    transitions = raw_transitions if isinstance(raw_transitions, list) else []
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        source_state = transition.get("from")
        target_state = transition.get("to")
        if source_state not in state_ids and source_state not in states:
            continue
        if target_state not in state_ids and target_state not in states:
            continue
        source_id = "%s::%s" % (definition_id, source_state)
        target_id = "%s::%s" % (definition_id, target_state)
        edges.append(
            _make_edge(
                "transition",
                source_id,
                target_id,
                _transition_label(transition.get("trigger"), transition.get("guard")),
            )
        )
    # 迁移的数组顺序由原 IR 决定；边 id 统一由 _finalize_edges 合成（含 #序号，保证唯一）。

    name = primary.get("name")
    return _view(
        "state-flight-modes",
        definition_id,
        "状态机视图：%s" % (name if isinstance(name, str) and name else definition_id),
        "State Transition View：states 合成 `<StateDefinition id>::<state>` 节点，"
        "transitions 成边（label = trigger，guard 以 `[if (...)]` 附后）；初始态用 attrs.initial 标注。",
        nodes,
        edges,
    )


def _transition_label(trigger: Any, guard: Any) -> str:
    """迁移边的展示标签：trigger 为主，guard 以 ``[if (...)]`` 附后。"""
    trigger_text = trigger.strip() if isinstance(trigger, str) else ""
    guard_text = guard.strip() if isinstance(guard, str) else ""
    if trigger_text and guard_text:
        return "%s [if (%s)]" % (trigger_text, guard_text)
    if trigger_text:
        return trigger_text
    if guard_text:
        return "if (%s)" % guard_text
    return ""


# --------------------------------------------------------------------------------------
# 视图拼装 / 节点与边
# --------------------------------------------------------------------------------------


def _view(
    view_id: str,
    scope: str,
    title: str,
    description: str,
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> Dict[str, Any]:
    ordered_nodes = sorted(nodes, key=_node_sort_key)
    return {
        "viewId": view_id,
        "kind": VIEW_KINDS[view_id],
        "scope": scope,
        "title": title,
        "description": description,
        "nodes": ordered_nodes,
        "edges": _finalize_edges(edges),
        "groups": _group_nodes(ordered_nodes),
    }


def _make_node(
    element: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
    node_ids: set,
) -> Dict[str, Any]:
    """按节点契约挑字段：只带展示需要的属性，不整份复制 IR 元素。"""
    element_id = element["id"]
    kind = element.get("kind")
    name = element.get("name")
    owner = element.get("owner")
    owner_text = owner if isinstance(owner, str) and owner else None
    return {
        "id": element_id,
        "kind": kind if isinstance(kind, str) else "",
        "label": name if isinstance(name, str) and name else element_id,
        "owner": owner_text,
        "parent": owner_text if owner_text in node_ids else None,
        "attrs": _display_attrs(element, by_id),
    }


def _display_attrs(element: Dict[str, Any], by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """按 kind 只挑**展示需要**的字段；值一律规范化，保证与 IR 键序无关。"""
    kind = element.get("kind")
    props = _props(element)
    attrs: Dict[str, Any] = {}

    description = props.get("description")
    if isinstance(description, str) and description:
        attrs["description"] = description

    if kind == "PartDefinition":
        if "isAbstract" in props:
            attrs["isAbstract"] = bool(props["isAbstract"])
    elif kind == "PartUsage":
        type_ref = props.get("typeRef")
        if isinstance(type_ref, str) and type_ref:
            attrs["typeRef"] = type_ref
            target = by_id.get(type_ref)
            if isinstance(target, dict) and isinstance(target.get("name"), str):
                attrs["typeName"] = target["name"]
        quantity = props.get("quantity")
        if isinstance(quantity, (int, float)) and not isinstance(quantity, bool):
            attrs["quantity"] = quantity
    elif kind == "Requirement":
        for field in ("text", "acceptanceCriteria", "verifyMethod", "priority", "source", "rationale"):
            value = props.get(field)
            if isinstance(value, str) and value:
                attrs[field] = value
        thresholds = {
            key: _canonical_value(props[key])
            for key in sorted(props)
            if key not in REQUIREMENT_STRING_FIELDS
        }
        if thresholds:
            attrs["thresholds"] = thresholds
    elif kind == "Attribute":
        if isinstance(props.get("valueType"), str) and props["valueType"]:
            attrs["valueType"] = props["valueType"]
        if "defaultValue" in props:
            attrs["defaultValue"] = _canonical_value(props["defaultValue"])
        if isinstance(props.get("unit"), str) and props["unit"]:
            attrs["unit"] = props["unit"]
    elif kind == "Constraint":
        if isinstance(props.get("expression"), str) and props["expression"]:
            attrs["expression"] = props["expression"]
        parameters = props.get("parameters")
        if isinstance(parameters, list):
            attrs["parameters"] = [_canonical_value(item) for item in parameters]
    elif kind == "Connection":
        for field in ("sourceRef", "targetRef", "flowKind"):
            value = props.get(field)
            if isinstance(value, str) and value:
                attrs[field] = value
    # StateDefinition 的 states/initial 由 state-flight-modes 视图的合成节点承载，
    # 这里不再重复放 `initial`（同名字段在不同节点上语义必须一致）。
    elif kind == "ActionDefinition":
        for field in ("inputs", "outputs"):
            if field in props:
                attrs[field] = _copy_ports(props[field])

    return attrs


def _copy_ports(value: Any) -> List[Dict[str, Any]]:
    ports: List[Dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        port: Dict[str, Any] = {}
        for field in ("name", "typeRef", "unit"):
            if field in item:
                port[field] = _canonical_value(item[field])
        ports.append(port)
    return ports


def _make_edge(
    kind: str,
    source: str,
    target: str,
    label: str = "",
    rationale: Any = None,
) -> Dict[str, Any]:
    """建一条边；``id`` 先留空，由 ``_finalize_edges`` 统一合成并排序。"""
    edge: Dict[str, Any] = {
        "id": "",
        "kind": kind,
        "source": source,
        "target": target,
        "label": label if isinstance(label, str) else "",
    }
    if isinstance(rationale, str) and rationale:
        edge["rationale"] = rationale
    return edge


def _finalize_edges(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给边合成稳定 id，并按 ``(kind, source, target, id)`` 升序返回。

    先按内容（kind/source/target/label/rationale）排序再分配序号，因此即使输入
    ``elements`` 顺序被打乱，同一组边的 id 也完全一致。
    """

    def content_key(edge: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
        return (
            edge["kind"],
            edge["source"],
            edge["target"],
            edge.get("label") or "",
            edge.get("rationale") or "",
        )

    counters: Dict[Tuple[str, str, str], int] = {}
    for edge in sorted(edges, key=content_key):
        pair = (edge["kind"], edge["source"], edge["target"])
        ordinal = counters.get(pair, 0)
        counters[pair] = ordinal + 1
        edge["id"] = "%s:%s->%s#%d" % (
            edge["kind"],
            edge["source"],
            edge["target"],
            ordinal,
        )
    return sorted(edges, key=lambda edge: (edge["kind"], edge["source"], edge["target"], edge["id"]))


def _group_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 kind 分组（前端「按类别」树的直接数据源），组序与组内 id 都确定。"""
    buckets: Dict[str, List[str]] = {}
    for node in nodes:
        buckets.setdefault(node["kind"], []).append(node["id"])

    ordered_kinds = list(NODE_KIND_ORDER) + [
        kind for kind in sorted(buckets) if kind not in NODE_KIND_ORDER
    ]
    groups: List[Dict[str, Any]] = []
    for kind in ordered_kinds:
        ids = buckets.get(kind)
        if not ids:
            continue
        groups.append(
            {
                "groupId": "kind:" + kind,
                "label": kind,
                "kind": kind,
                "nodeIds": sorted(ids),
                "count": len(ids),
            }
        )
    return groups


def _node_sort_key(node: Dict[str, Any]) -> Tuple[int, str]:
    kind = node.get("kind")
    rank = NODE_KIND_ORDER.index(kind) if kind in NODE_KIND_ORDER else len(NODE_KIND_ORDER)
    return rank, node["id"]


# --------------------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------------------


def _coerce_model(model: Any) -> Tuple[Any, Optional[str]]:
    if isinstance(model, (str, bytes, bytearray)):
        try:
            return json.loads(model), None
        except Exception as exc:  # noqa: BLE001 - 输入来自 LLM/外部文件
            return None, "输入不是合法 JSON：%s" % exc
    return model, None


def _index(
    model: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], str]:
    raw = model.get("elements")
    elements = [
        element
        for element in (raw if isinstance(raw, list) else [])
        if isinstance(element, dict) and isinstance(element.get("id"), str) and element["id"]
    ]
    by_id: Dict[str, Dict[str, Any]] = {}
    for element in elements:
        by_id.setdefault(element["id"], element)
    package = model.get("package")
    return elements, by_id, package if isinstance(package, str) else ""


def _relation_count(elements: List[Dict[str, Any]]) -> int:
    return sum(len(_relations(element)) for element in elements)


def _relations(element: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = element.get("relations")
    if not isinstance(raw, list):
        return []
    return [relation for relation in raw if isinstance(relation, dict)]


def _props(element: Dict[str, Any]) -> Dict[str, Any]:
    properties = element.get("properties")
    return properties if isinstance(properties, dict) else {}


def _canonical_value(value: Any) -> Any:
    """递归排序 dict 键，消除 IR 对象键序对输出字节的影响。"""
    if isinstance(value, dict):
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    return value


def _owner_chain_contains(
    element: Dict[str, Any],
    ancestor_id: str,
    by_id: Dict[str, Dict[str, Any]],
) -> bool:
    """``ancestor_id`` 是否在元素的 owner 链上（不含元素自身）。"""
    owner = element.get("owner")
    seen: set = set()
    while isinstance(owner, str) and owner and owner not in seen:
        if owner == ancestor_id:
            return True
        seen.add(owner)
        parent = by_id.get(owner)
        if parent is None:
            return False
        owner = parent.get("owner")
    return False


def _stats(elements: List[Dict[str, Any]], views: List[Dict[str, Any]]) -> Dict[str, Any]:
    elements_by_kind: Dict[str, int] = {kind: 0 for kind in KIND_ORDER}
    for element in elements:
        kind = element.get("kind")
        if kind in elements_by_kind:
            elements_by_kind[kind] += 1
    relations_by_type: Dict[str, int] = {relation_type: 0 for relation_type in RELATION_ORDER}
    for element in elements:
        for relation in _relations(element):
            relation_type = relation.get("type")
            if relation_type in relations_by_type:
                relations_by_type[relation_type] += 1
    return {
        "viewCount": len(views),
        "nodeCount": sum(len(view["nodes"]) for view in views),
        "edgeCount": sum(len(view["edges"]) for view in views),
        "elementsByKind": elements_by_kind,
        "relationsByType": relations_by_type,
    }


def _stats_with_views(stats: Dict[str, Any], views: List[Dict[str, Any]]) -> Dict[str, Any]:
    updated = dict(stats)
    updated["viewCount"] = len(views)
    updated["nodeCount"] = sum(len(view["nodes"]) for view in views)
    updated["edgeCount"] = sum(len(view["edges"]) for view in views)
    return updated


def _error(code: str, message: str, element: Optional[str] = None) -> Dict[str, Any]:
    return {"code": code, "element": element, "message": message}


def _failure(errors: List[Dict[str, Any]], warnings: Optional[List[Any]] = None) -> Dict[str, Any]:
    return {"ok": False, "graph": None, "errors": errors, "warnings": list(warnings or [])}


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _run_cli(args: argparse.Namespace) -> Dict[str, Any]:
    try:
        with open(args.input, "r", encoding="utf-8") as handle:
            model = json.load(handle)
    except FileNotFoundError:
        return _failure([_error("E-GRAPH-INPUT", "输入文件不存在：`%s`。" % args.input)])
    except IsADirectoryError:
        return _failure([_error("E-GRAPH-INPUT", "输入路径是目录，不是 IR JSON 文件：`%s`。" % args.input)])
    except UnicodeDecodeError as exc:
        return _failure(
            [_error("E-GRAPH-INPUT", "输入文件不是 UTF-8 文本：`%s`（%s）。" % (args.input, exc))]
        )
    except json.JSONDecodeError as exc:
        return _failure(
            [_error("E-GRAPH-INPUT", "输入文件不是合法 JSON：`%s`（%s）。" % (args.input, exc))]
        )
    except OSError as exc:
        return _failure([_error("E-GRAPH-INPUT", "读取输入文件失败：`%s`（%s）。" % (args.input, exc))])

    if args.check:
        validation = validate_model_json(model)
        return {
            "ok": bool(validation.get("ok")),
            "input": args.input,
            "errors": list(validation.get("errors") or []),
            "warnings": list(validation.get("warnings") or []),
            "schemaLayer": validation.get("schemaLayer"),
        }

    result = build_graph(model)
    if not result.get("ok") or args.view is None:
        return result

    graph = result.get("graph") or {}
    views = [view for view in graph.get("views", []) if view.get("viewId") == args.view]
    if not views:
        return _failure(
            [
                _error(
                    "E-GRAPH-VIEW-UNKNOWN",
                    "未知 viewId `%s`；可用：%s。" % (args.view, "、".join(VIEW_ORDER)),
                )
            ],
            result.get("warnings") or [],
        )
    filtered = {
        "schema": graph.get("schema"),
        "modelRef": graph.get("modelRef"),
        "views": views,
        "stats": _stats_with_views(graph.get("stats") or {}, views),
    }
    return {"ok": True, "graph": filtered, "errors": [], "warnings": result.get("warnings") or []}


def _emit(payload: Dict[str, Any], output: Optional[str]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output is None or output == "-":
        sys.stdout.write(text)
        return
    path = Path(output).expanduser()
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    summary: Dict[str, Any] = {"ok": payload.get("ok"), "output": str(path)}
    graph = payload.get("graph")
    if isinstance(graph, dict):
        stats = graph.get("stats") or {}
        summary["viewCount"] = len(graph.get("views") or [])
        summary["nodeCount"] = stats.get("nodeCount")
        summary["edgeCount"] = stats.get("edgeCount")
        model_ref = graph.get("modelRef") or {}
        summary["contentSha256"] = model_ref.get("contentSha256")
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="graph.py",
        description="IR JSON → sysml-graph/v1 图投影（纯标准库、确定性）。",
    )
    parser.add_argument("--input", required=True, help="输入 IR JSON 文件路径")
    parser.add_argument(
        "--output",
        default=None,
        help="输出 JSON 文件路径；`-` 或省略时写标准输出（失败时返回非 0 退出码）",
    )
    parser.add_argument("--view", default=None, help="只输出指定 viewId（调试用）")
    parser.add_argument("--check", action="store_true", help="只校验输入，输出 ok/errors")
    args = parser.parse_args(argv)

    result = _run_cli(args)
    try:
        _emit(result, args.output)
    except OSError as exc:
        failed = _failure([_error("E-GRAPH-OUTPUT", "写出输出文件失败：%s。" % exc)])
        _emit(failed, None)
        return 1
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
