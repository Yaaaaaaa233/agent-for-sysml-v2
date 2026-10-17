"""``patch_model`` —— 对已有 IR JSON 做增量编辑（原子补丁）。

技术方案 5.2 的二期能力：模型改一处不必重吐整份 JSON。LLM 只需描述「改哪一步」，
本工具在深拷贝上依次应用，**任何一步失败或补丁后校验不通过就整体回滚**，
绝不返回半应用的模型——这是「IR JSON 是唯一事实来源」的底线。

支持的 op（``ops`` 数组元素）：

============= ============================================ ==========================
``op``        必填字段                                     说明
============= ============================================ ==========================
add_element   ``element``                                  新增元素；``element.id`` 不得与现有 id 重复
update_element ``id`` + ``element``（完整元素）             整体替换；``element.id`` 必须等于 ``id``
remove_element ``id``；可选 ``cascade``（默认 ``false``）    默认拒绝删除仍被引用的元素；``cascade`` 时级联清理
add_relation  ``id`` + ``relation`` {type,target,rationale} 往宿主元素的 ``relations`` 追加一条
remove_relation ``id`` + ``type`` + ``target``               精确删除宿主元素上第一条同型同目标的关系
============= ============================================ ==========================

「引用」的口径与 ``query_model(referrers_of=...)`` 一致，并额外算上 ``owner``：
``relations[].target``、``properties.typeRef``、``owner`` 三条边都算。

``cascade=true`` 的清理规则（逐条写进 diff）：

- 指向被删元素的 ``relations`` 项 → 直接摘除（关系可以不存在，元素仍然合法）；
- ``properties.typeRef`` 指向被删元素的元素 → **整个元素一并删除**。``typeRef`` 是
  ``PartUsage`` 的必填字段，摘掉引用会让它变成非法模型，因此只能连元素一起删；
- ``owner`` 指向被删元素的子元素 → **整棵子树一并删除**（父元素没了，子元素无处挂靠）。

返回值恒为 ``{"ok", "model", "diff", "errors", "warnings"}``；
``ok=false`` 时 ``model`` 一定为 ``None``（不回传半应用结果），
``diff`` 里已执行的步骤会标注「已回滚，未生效」。

``diff`` 每条为 ``{"change": "+|-|~", "kind": "element|relation", "id", "detail"}``。
``kind="relation"`` 时 ``id`` 取**宿主元素**的 id，``detail`` 里写明 ``type → target``。

错误码（建议合入 ``schema/字段说明.md`` §6.1）：

- ``E-PATCH-MODEL-INVALID``：``model`` 不是对象 / 不是合法 JSON / ``elements`` 不是数组
- ``E-PATCH-OPS-NOT-ARRAY``：``ops`` 不是数组
- ``E-PATCH-OP-INVALID``：``ops[i]`` 不是对象
- ``E-PATCH-UNKNOWN-OP``：``op`` 不在受支持列表内
- ``E-PATCH-ID-MISSING``：op 缺少合法的 ``id``（或 ``element.id``）
- ``E-PATCH-ID-NOTFOUND``：``update/remove`` 的 ``id`` 在模型内不存在
- ``E-PATCH-ID-DUP``：``add_element`` 的 id 已被占用
- ``E-PATCH-ID-MISMATCH``：``update_element.element.id`` 与 ``id`` 不一致
- ``E-PATCH-ELEMENT-INVALID``：``element`` 不是对象
- ``E-REF-DEPENDENT``：``remove_element`` 默认模式下元素仍被引用（逐条列出引用方）
- ``E-PATCH-REL-INVALID``：``relation`` 不是对象 / 缺 ``type`` 或 ``target``
- ``E-PATCH-REL-NOT-ARRAY``：宿主元素的 ``relations`` 不是数组
- ``E-PATCH-REL-DUP``：``add_relation`` 的 type+target 已存在
- ``E-PATCH-REL-NOTFOUND``：``remove_relation`` 找不到匹配项
- ``E-PATCH-VALIDATE-FAILED``：补丁后 ``validate_model_json`` 仍报错（其后各条为底层的原始错误）

纯函数：不修改传入的 ``model``；所有操作都在深拷贝上完成。
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional, Tuple

from .validator import validate_model_json

#: 支持的 op 名（顺序即文档中的展示顺序）
SUPPORTED_OPS: Tuple[str, ...] = (
    "add_element",
    "update_element",
    "remove_element",
    "add_relation",
    "remove_relation",
)


def patch_model(model: Any, ops: Any, validate: bool = True) -> Dict[str, Any]:
    """对 IR JSON 应用一组增量补丁（原子操作）。

    :param model: IR JSON（dict 或 JSON 字符串）
    :param ops: op 数组，见模块 docstring 的表格
    :param validate: 补丁后是否跑 ``validate_model_json``（默认 ``True``；
        传 ``False`` 仅供调试，此时可能得到语义非法的模型）
    :return: ``{"ok", "model", "diff", "errors", "warnings"}``；
        失败时 ``model`` 为 ``None``，``diff`` 说明已执行但被回滚的步骤
    """
    working, error = _coerce_model(model)
    if error is not None:
        return _failure(
            [_error("E-PATCH-MODEL-INVALID", None, error, None)], [], []
        )

    if not isinstance(working.get("elements"), list):
        return _failure(
            [
                _error(
                    "E-PATCH-MODEL-INVALID",
                    None,
                    "IR 的 `elements` 必须是数组，增量编辑无从下手（实际为 %s）。"
                    % _type_name(working.get("elements")),
                    None,
                )
            ],
            [],
            [],
        )

    if not isinstance(ops, list):
        return _failure(
            [
                _error(
                    "E-PATCH-OPS-NOT-ARRAY",
                    None,
                    "`ops` 必须是数组（每个元素是一个 op 对象），实际为 %s。"
                    % _type_name(ops),
                    None,
                )
            ],
            [],
            [],
        )

    # 深拷贝：绝不碰调用方的对象，也便于失败时整体丢弃。
    patched: Dict[str, Any] = copy.deepcopy(working)
    diff: List[Dict[str, Any]] = []

    for index, op in enumerate(ops):
        step_errors = _apply_op(patched, op, index, diff)
        if step_errors:
            _mark_rolled_back(diff)
            return _failure(step_errors, diff, [])

    warnings: List[Dict[str, Any]] = []
    if validate is not False:
        result = validate_model_json(patched)
        warnings = list(result.get("warnings") or [])
        if not result.get("ok"):
            validation_errors = [dict(item) for item in result.get("errors") or []]
            summary = _error(
                "E-PATCH-VALIDATE-FAILED",
                None,
                "补丁后校验仍有 %d 条 error，已整体回滚，未返回模型。"
                "请改 JSON 后重试（其后各条为校验器原始错误）。" % len(validation_errors),
                None,
            )
            _mark_rolled_back(diff)
            return _failure([summary] + validation_errors, diff, warnings)

    return {
        "ok": True,
        "model": patched,
        "diff": diff,
        "errors": [],
        "warnings": warnings,
    }


# --------------------------------------------------------------------------------------
# op 分发
# --------------------------------------------------------------------------------------


def _apply_op(
    model: Dict[str, Any],
    op: Any,
    index: int,
    diff: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """应用单个 op；成功返回空列表，失败返回错误列表（且不留下任何修改）。"""
    if not isinstance(op, dict):
        return [
            _error(
                "E-PATCH-OP-INVALID",
                None,
                "ops[%d] 必须是对象（含 `op` 字段），实际为 %s。" % (index, _type_name(op)),
                index,
            )
        ]

    name = op.get("op")
    handler = _HANDLERS.get(name) if isinstance(name, str) else None
    if handler is None:
        return [
            _error(
                "E-PATCH-UNKNOWN-OP",
                None,
                "ops[%d].op = %s 不受支持；允许值：%s。"
                % (index, _repr(name), "、".join(SUPPORTED_OPS)),
                index,
            )
        ]
    return handler(model, op, index, diff)


def _op_add_element(
    model: Dict[str, Any],
    op: Dict[str, Any],
    index: int,
    diff: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    element = op.get("element")
    if not isinstance(element, dict):
        return [
            _error(
                "E-PATCH-ELEMENT-INVALID",
                None,
                "add_element.element 必须是对象，实际为 %s。" % _type_name(element),
                index,
            )
        ]

    element_id, error = _require_id(element.get("id"), index, "add_element.element.id")
    if error is not None:
        return [error]
    if _find_index(model, element_id) >= 0:
        return [
            _error(
                "E-PATCH-ID-DUP",
                element_id,
                "add_element 的 id `%s` 已被占用；如需修改现有元素请用 update_element。" % element_id,
                index,
            )
        ]

    model["elements"].append(copy.deepcopy(element))
    diff.append(
        {
            "change": "+",
            "kind": "element",
            "id": element_id,
            "detail": "新增元素 %s。" % _element_label(element),
        }
    )
    return []


def _op_update_element(
    model: Dict[str, Any],
    op: Dict[str, Any],
    index: int,
    diff: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    element_id, error = _require_id(op.get("id"), index, "update_element.id")
    if error is not None:
        return [error]

    element = op.get("element")
    if not isinstance(element, dict):
        return [
            _error(
                "E-PATCH-ELEMENT-INVALID",
                element_id,
                "update_element.element 必须是完整元素对象（整体替换），实际为 %s。"
                % _type_name(element),
                index,
            )
        ]
    if element.get("id") != element_id:
        return [
            _error(
                "E-PATCH-ID-MISMATCH",
                element_id,
                "update_element.element.id = %s 与 op.id = `%s` 不一致；"
                "整体替换不允许顺手改 id。" % (_repr(element.get("id")), element_id),
                index,
            )
        ]

    position = _find_index(model, element_id)
    if position < 0:
        return [
            _error(
                "E-PATCH-ID-NOTFOUND",
                element_id,
                "update_element 的 id `%s` 在模型内不存在。" % element_id,
                index,
            )
        ]

    old = model["elements"][position]
    replacement = copy.deepcopy(element)
    model["elements"][position] = replacement
    diff.append(
        {
            "change": "~",
            "kind": "element",
            "id": element_id,
            "detail": "整体替换 %s；%s"
            % (_element_label(replacement), _describe_update(old, replacement)),
        }
    )
    return []


def _op_remove_element(
    model: Dict[str, Any],
    op: Dict[str, Any],
    index: int,
    diff: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    element_id, error = _require_id(op.get("id"), index, "remove_element.id")
    if error is not None:
        return [error]

    position = _find_index(model, element_id)
    if position < 0:
        return [
            _error(
                "E-PATCH-ID-NOTFOUND",
                element_id,
                "remove_element 的 id `%s` 在模型内不存在。" % element_id,
                index,
            )
        ]

    cascade = bool(op.get("cascade", False))
    dependents = _dependents(model, element_id)

    if not cascade:
        if dependents:
            return [
                _error(
                    "E-REF-DEPENDENT",
                    element_id,
                    "`%s` 仍被 `%s` 引用（via %s）；remove_element 默认拒绝删除。"
                    "确认要连带清理时传 cascade=true，或先手工解除引用。"
                    % (element_id, item["id"], item["via"]),
                    index,
                )
                for item in dependents
            ]
        label = _element_label(model["elements"][position])
        del model["elements"][position]
        diff.append(
            {
                "change": "-",
                "kind": "element",
                "id": element_id,
                "detail": "删除元素 %s。" % label,
            }
        )
        return []

    return _cascade_remove(model, element_id, index, diff)


def _op_add_relation(
    model: Dict[str, Any],
    op: Dict[str, Any],
    index: int,
    diff: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    element_id, error = _require_id(op.get("id"), index, "add_relation.id")
    if error is not None:
        return [error]

    relation = op.get("relation")
    if not isinstance(relation, dict):
        return [
            _error(
                "E-PATCH-REL-INVALID",
                element_id,
                "add_relation.relation 必须是对象 {type,target,rationale}，实际为 %s。"
                % _type_name(relation),
                index,
            )
        ]

    rel_type, rel_target, rel_error = _require_relation_key(relation, element_id, index)
    if rel_error is not None:
        return [rel_error]

    position = _find_index(model, element_id)
    if position < 0:
        return [
            _error(
                "E-PATCH-ID-NOTFOUND",
                element_id,
                "add_relation 的宿主 id `%s` 在模型内不存在。" % element_id,
                index,
            )
        ]

    element = model["elements"][position]
    relations = element.get("relations")
    if relations is None:
        relations = []
    elif not isinstance(relations, list):
        return [
            _error(
                "E-PATCH-REL-NOT-ARRAY",
                element_id,
                "宿主元素 `%s` 的 relations 必须是数组，实际为 %s。"
                % (element_id, _type_name(relations)),
                index,
            )
        ]

    for existing in relations:
        if not isinstance(existing, dict):
            continue
        if existing.get("type") == rel_type and existing.get("target") == rel_target:
            return [
                _error(
                    "E-PATCH-REL-DUP",
                    element_id,
                    "宿主 `%s` 上已存在 %s → `%s` 的关系，未重复添加。"
                    % (element_id, rel_type, rel_target),
                    index,
                )
            ]

    element["relations"] = relations
    relations.append(copy.deepcopy(relation))
    diff.append(
        {
            "change": "+",
            "kind": "relation",
            "id": element_id,
            "detail": "新增关系：宿主 `%s` 的 %s → `%s`。" % (element_id, rel_type, rel_target),
        }
    )
    return []


def _op_remove_relation(
    model: Dict[str, Any],
    op: Dict[str, Any],
    index: int,
    diff: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    element_id, error = _require_id(op.get("id"), index, "remove_relation.id")
    if error is not None:
        return [error]

    rel_type = op.get("type")
    rel_target = op.get("target")
    if not _is_nonempty_str(rel_type) or not _is_nonempty_str(rel_target):
        return [
            _error(
                "E-PATCH-REL-INVALID",
                element_id,
                "remove_relation 需要非空字符串 `type` 与 `target`（实际 type=%s、target=%s）。"
                % (_repr(rel_type), _repr(rel_target)),
                index,
            )
        ]

    position = _find_index(model, element_id)
    if position < 0:
        return [
            _error(
                "E-PATCH-ID-NOTFOUND",
                element_id,
                "remove_relation 的宿主 id `%s` 在模型内不存在。" % element_id,
                index,
            )
        ]

    element = model["elements"][position]
    relations = element.get("relations")
    if relations is not None and not isinstance(relations, list):
        return [
            _error(
                "E-PATCH-REL-NOT-ARRAY",
                element_id,
                "宿主元素 `%s` 的 relations 必须是数组，实际为 %s。"
                % (element_id, _type_name(relations)),
                index,
            )
        ]
    if not isinstance(relations, list):
        relations = []

    for relation_position, relation in enumerate(relations):
        if not isinstance(relation, dict):
            continue
        if relation.get("type") == rel_type and relation.get("target") == rel_target:
            del relations[relation_position]
            diff.append(
                {
                    "change": "-",
                    "kind": "relation",
                    "id": element_id,
                    "detail": "删除关系：宿主 `%s` 的 %s → `%s`。"
                    % (element_id, rel_type, rel_target),
                }
            )
            return []

    return [
        _error(
            "E-PATCH-REL-NOTFOUND",
            element_id,
            "宿主 `%s` 上找不到 %s → `%s` 的关系。" % (element_id, rel_type, rel_target),
            index,
        )
    ]


_HANDLERS = {
    "add_element": _op_add_element,
    "update_element": _op_update_element,
    "remove_element": _op_remove_element,
    "add_relation": _op_add_relation,
    "remove_relation": _op_remove_relation,
}


# --------------------------------------------------------------------------------------
# 引用分析与级联
# --------------------------------------------------------------------------------------


def _dependents(model: Dict[str, Any], target: str) -> List[Dict[str, Any]]:
    """列出所有引用 ``target`` 的元素（relations.target / properties.typeRef / owner）。"""
    dependents: List[Dict[str, Any]] = []
    for element in model["elements"]:
        if not isinstance(element, dict):
            continue
        element_id = element.get("id")
        if not isinstance(element_id, str) or element_id == target:
            continue

        if element.get("owner") == target:
            dependents.append({"id": element_id, "via": "owner"})

        properties = element.get("properties")
        if isinstance(properties, dict) and properties.get("typeRef") == target:
            dependents.append({"id": element_id, "via": "properties.typeRef"})

        for relation in element.get("relations") or []:
            if not isinstance(relation, dict) or relation.get("target") != target:
                continue
            dependents.append(
                {
                    "id": element_id,
                    "via": "relations.%s" % relation.get("type"),
                }
            )
    return dependents


def _cascade_remove(
    model: Dict[str, Any],
    root_id: str,
    index: int,
    diff: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """级联删除：先算出闭包，再一次性落盘（失败前不会留下半成品）。"""
    elements = model["elements"]
    removed: Dict[str, str] = {root_id: "根元素"}
    frontier = [root_id]

    while frontier:
        current = frontier.pop()
        for element in elements:
            if not isinstance(element, dict):
                continue
            element_id = element.get("id")
            if not isinstance(element_id, str) or element_id in removed:
                continue
            properties = element.get("properties")
            if element.get("owner") == current:
                removed[element_id] = "owner 指向 `%s`" % current
                frontier.append(element_id)
            elif isinstance(properties, dict) and properties.get("typeRef") == current:
                removed[element_id] = "properties.typeRef 指向 `%s`" % current
                frontier.append(element_id)

    # 幸存元素上指向被删集合的关系项，逐条记录后摘除。
    stripped: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        if element.get("id") in removed:
            continue
        relations = element.get("relations")
        if not isinstance(relations, list):
            continue
        for relation in relations:
            if isinstance(relation, dict) and relation.get("target") in removed:
                stripped.append((element, relation))

    # 真正的修改从这里开始（此前全是只读计算）。
    for element, relation in stripped:
        relations = element.get("relations")
        if isinstance(relations, list):
            element["relations"] = [item for item in relations if item is not relation]

    removed_elements: List[Dict[str, Any]] = [
        element
        for element in elements
        if isinstance(element, dict) and element.get("id") in removed
    ]
    model["elements"] = [
        element
        for element in elements
        if not (isinstance(element, dict) and element.get("id") in removed)
    ]

    root = next(
        (element for element in removed_elements if element.get("id") == root_id),
        {"id": root_id},
    )
    cascaded_ids = [element.get("id") for element in removed_elements if element.get("id") != root_id]
    diff.append(
        {
            "change": "-",
            "kind": "element",
            "id": root_id,
            "detail": "删除元素 %s；级联删除 %d 个元素、摘除 %d 条关系。"
            % (_element_label(root), len(cascaded_ids), len(stripped)),
        }
    )

    for element in removed_elements:
        element_id = element.get("id")
        if element_id == root_id:
            continue
        diff.append(
            {
                "change": "-",
                "kind": "element",
                "id": element_id,
                "detail": "级联删除 %s（%s，无法独立存活）。"
                % (_element_label(element), removed.get(element_id, "被引用")),
            }
        )

    for element, relation in stripped:
        element_id = element.get("id")
        diff.append(
            {
                "change": "-",
                "kind": "relation",
                "id": element_id,
                "detail": "级联删除关系：宿主 `%s` 的 %s → `%s`（目标已被删除）。"
                % (element_id, relation.get("type"), relation.get("target")),
            }
        )
    return []


# --------------------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------------------


def _coerce_model(model: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if isinstance(model, (str, bytes, bytearray)):
        try:
            model = json.loads(model)
        except Exception as exc:  # noqa: BLE001 - 输入来自 LLM，宽进严出
            return None, "输入不是合法 JSON：%s" % exc
    if not isinstance(model, dict):
        return None, "IR 顶层必须是 JSON 对象，实际为 %s。" % _type_name(model)
    return model, None


def _failure(
    errors: List[Dict[str, Any]],
    diff: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "ok": False,
        "model": None,
        "diff": diff,
        "errors": errors,
        "warnings": warnings,
    }


def _mark_rolled_back(diff: List[Dict[str, Any]]) -> None:
    """失败时给已执行的 diff 条目补一句「已回滚」，让调用方别误以为生效了。"""
    for entry in diff:
        detail = entry.get("detail")
        if isinstance(detail, str) and "已回滚" not in detail:
            entry["detail"] = detail + "（该步骤已回滚，未生效）"


def _error(
    code: str,
    element: Optional[str],
    message: str,
    step: Optional[int],
) -> Dict[str, Any]:
    return {"code": code, "element": element, "message": message, "step": step}


def _require_id(value: Any, step: int, label: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if not _is_nonempty_str(value):
        return None, _error(
            "E-PATCH-ID-MISSING",
            None,
            "%s 必须是非空字符串（元素 id），实际为 %s。" % (label, _repr(value)),
            step,
        )
    return value, None


def _require_relation_key(
    relation: Dict[str, Any],
    element_id: str,
    step: int,
) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    rel_type = relation.get("type")
    rel_target = relation.get("target")
    if not _is_nonempty_str(rel_type) or not _is_nonempty_str(rel_target):
        return None, None, _error(
            "E-PATCH-REL-INVALID",
            element_id,
            "relation 需要非空字符串 `type` 与 `target`（实际 type=%s、target=%s）；"
            "`rationale` 的必填性由校验器把关。" % (_repr(rel_type), _repr(rel_target)),
            step,
        )
    return rel_type, rel_target, None


def _find_index(model: Dict[str, Any], element_id: str) -> int:
    for index, element in enumerate(model["elements"]):
        if isinstance(element, dict) and element.get("id") == element_id:
            return index
    return -1


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _element_label(element: Dict[str, Any]) -> str:
    element_id = element.get("id")
    kind = element.get("kind")
    name = element.get("name")
    if isinstance(kind, str) and isinstance(name, str):
        return "`%s` `%s`（id=`%s`）" % (kind, name, element_id)
    return "`%s`" % element_id


def _describe_update(old: Any, new: Any) -> str:
    if not isinstance(old, dict) or not isinstance(new, dict):
        return "结构已变化。"
    changed: List[str] = []
    for key in sorted(set(old) | set(new)):
        if old.get(key) == new.get(key):
            continue
        if key == "properties" and isinstance(old.get(key), dict) and isinstance(new.get(key), dict):
            old_props = old[key]
            new_props = new[key]
            for sub_key in sorted(set(old_props) | set(new_props)):
                if old_props.get(sub_key) != new_props.get(sub_key):
                    changed.append("properties.%s" % sub_key)
            continue
        changed.append(str(key))
    if not changed:
        changed.append("（无字段差异）")
    return "变更字段：%s。" % "、".join(changed)


def _repr(value: Any) -> str:
    if isinstance(value, str):
        return "`%s`" % value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return repr(value)


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


# --------------------------------------------------------------------------------------
# CLI：python -m tools.patch <ir.json> <ops.json>
# --------------------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    from .validator import load_model

    if len(sys.argv) != 3:
        print("用法：python -m tools.patch <ir.json> <ops.json>")
        raise SystemExit(2)
    with open(sys.argv[2], "r", encoding="utf-8") as handle:
        operations = json.load(handle)
    print(json.dumps(patch_model(load_model(sys.argv[1]), operations),
                     ensure_ascii=False, indent=2))
