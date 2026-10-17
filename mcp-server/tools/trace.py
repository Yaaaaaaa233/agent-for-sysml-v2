"""``traceability`` —— 需求追溯矩阵、覆盖缺口与影响面分析。

技术方案 9.1 的 T9（MVP 留到二期的「追溯检查」）。它把散落在 ``relations`` 里的
追溯关系整理成一张**可读、可核对**的表：

1. **矩阵**：每条 ``Requirement`` 一行，给出 ``satisfiedBy``（谁满足它）与
   ``verifiedBy``（谁验证它），并合成四种状态：

   - ``satisfied-and-verified``：既被满足、又被验证（健康）
   - ``satisfied``：只被满足，没人验证
   - ``verified-only``：只被验证，没人满足
   - ``unsatisfied``：既没人满足、也没人验证

2. **缺口**：未满足的需求、未被验证的需求，以及「没有任何 ``verifies`` 关系」的
   ``ActionDefinition``（方案里说的「没人验证的功能」）。

3. **影响面**（可选 ``focus``）：按引用关系做**反向** BFS——谁引用了它、引用它的人
   又被谁引用。引用边三条：``relations[].target``、``PartUsage.typeRef``（泛化为
   任意 ``properties.typeRef``）、``owner``（子元素）。``focus`` 可以是单个 id，
   也可以是 id 列表（多源 BFS）。

4. **Markdown**（``fmt="md"``）：把矩阵、缺口、影响面渲染成一份可直接贴进报告的
   Markdown 文本，放在 ``content`` 字段里；``fmt="json"`` 时 ``content`` 为 ``None``。

返回值恒为 ``{"ok", "matrix", "gaps", "impact", "content", "errors"}``。
``focus`` 未给出时 ``impact`` 为 ``None``。

错误码（建议合入 ``schema/字段说明.md`` §6.1）：

- ``E-INPUT-NOT-JSON``：``model`` 是字符串但不是合法 JSON
- ``E-ROOT-NOT-OBJECT``：``model`` 顶层不是对象
- ``E-TRACE-MODEL-INVALID``：``model.elements`` 不是数组
- ``E-TRACE-FMT-INVALID``：``fmt`` 不是 ``json`` / ``md``
- ``E-TRACE-FOCUS-INVALID``：``focus`` 不是字符串或字符串数组（含空字符串 / 空数组）
- ``E-TRACE-FOCUS-NOTFOUND``：``focus`` 里的 id 在模型内不存在（逐条列出）

纯函数：不修改传入的 ``model``；对未知 ``kind`` 保持通用（只按 id/kind/relations/
typeRef/owner 读，不硬编码元素种类清单）。

诚实口径：``content`` 只是把 IR 里**已经写了**的关系排版出来，不做任何语义推断；
需求是否真的被满足、动作是否真的能验证需求，仍需人判断。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

#: 需求行的四种状态
STATUSES: Tuple[str, ...] = (
    "satisfied-and-verified",
    "satisfied",
    "verified-only",
    "unsatisfied",
)

#: 需求摘要的截断长度（字符数，中文按 1 个字符算）
TEXT_SHORT_LIMIT = 60

_FORMATS = ("json", "md")


def traceability(
    model: Any,
    focus: Optional[Any] = None,
    fmt: str = "json",
) -> Dict[str, Any]:
    """生成追溯矩阵 / 缺口 / 影响面。

    :param model: IR JSON（dict 或 JSON 字符串）
    :param focus: 可选；单个元素 id 或 id 列表，给出时计算反向引用影响面
    :param fmt: ``"json"``（默认）或 ``"md"``（额外返回 Markdown 矩阵 ``content``）
    :return: ``{"ok", "matrix", "gaps", "impact", "content", "errors"}``
    """
    model, error, error_code = _coerce_model(model)
    if error is not None:
        return _failure([_error(error_code or "E-ROOT-NOT-OBJECT", error)])

    if fmt is None:
        fmt = "json"
    if fmt not in _FORMATS:
        return _failure(
            [
                _error(
                    "E-TRACE-FMT-INVALID",
                    "`fmt` 只能是 %s，实际为 %s。"
                    % (" / ".join(_FORMATS), _repr(fmt)),
                )
            ]
        )

    raw_elements = model.get("elements")
    if raw_elements is None:
        raw_elements = []
    if not isinstance(raw_elements, list):
        return _failure(
            [
                _error(
                    "E-TRACE-MODEL-INVALID",
                    "IR 的 `elements` 必须是数组，实际为 %s。"
                    % _type_name(raw_elements),
                )
            ]
        )
    elements = [item for item in raw_elements if isinstance(item, dict)]
    by_id = _index_by_id(elements)

    focus_ids: Optional[List[str]] = None
    if focus is not None:
        focus_ids, focus_error = _normalize_focus(focus, by_id)
        if focus_error is not None:
            return _failure([focus_error])

    matrix, gaps = _build_matrix(elements)
    impact = None
    if focus_ids is not None:
        impact = _impact(by_id, focus_ids)

    content = None
    if fmt == "md":
        content = _render_markdown(model, matrix, gaps, impact)

    return {
        "ok": True,
        "matrix": matrix,
        "gaps": gaps,
        "impact": impact,
        "content": content,
        "errors": [],
    }


# --------------------------------------------------------------------------------------
# 矩阵与缺口
# --------------------------------------------------------------------------------------


def _build_matrix(
    elements: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    """返回 ``(matrix, gaps)``。矩阵按 id 排序，保证同输入同输出。"""
    verifiers: Dict[str, List[str]] = {}
    unverified_actions: List[str] = []

    for element in sorted(elements, key=lambda item: str(item.get("id"))):
        element_id = element.get("id")
        if not isinstance(element_id, str):
            continue
        relations = [item for item in (element.get("relations") or []) if isinstance(item, dict)]
        relation_types = {relation.get("type") for relation in relations}

        if element.get("kind") == "ActionDefinition" and "verifies" not in relation_types:
            unverified_actions.append(element_id)

        for relation in relations:
            if relation.get("type") != "verifies":
                continue
            target = relation.get("target")
            if isinstance(target, str):
                verifiers.setdefault(target, []).append(element_id)

    matrix: List[Dict[str, Any]] = []
    unsatisfied: List[str] = []
    unverified_requirements: List[str] = []

    for element in sorted(elements, key=lambda item: str(item.get("id"))):
        if element.get("kind") != "Requirement":
            continue
        requirement_id = element.get("id")
        if not isinstance(requirement_id, str):
            continue

        satisfied_by = _relation_targets(element, "satisfiedBy")
        verified_by = _dedupe(verifiers.get(requirement_id, []))
        text = _text_of(element)

        if satisfied_by and verified_by:
            status = "satisfied-and-verified"
        elif satisfied_by:
            status = "satisfied"
        elif verified_by:
            status = "verified-only"
        else:
            status = "unsatisfied"

        if not satisfied_by:
            unsatisfied.append(requirement_id)
        if not verified_by:
            unverified_requirements.append(requirement_id)

        matrix.append(
            {
                "requirement": requirement_id,
                "name": element.get("name"),
                "text_short": _shorten(text),
                "satisfiedBy": satisfied_by,
                "verifiedBy": verified_by,
                "status": status,
            }
        )

    gaps = {
        "unsatisfied": sorted(unsatisfied),
        "unverified_requirement": sorted(unverified_requirements),
        "unverified_action": sorted(unverified_actions),
    }
    return matrix, gaps


def _relation_targets(element: Dict[str, Any], relation_type: str) -> List[str]:
    targets: List[str] = []
    for relation in element.get("relations") or []:
        if not isinstance(relation, dict) or relation.get("type") != relation_type:
            continue
        target = relation.get("target")
        if isinstance(target, str) and target not in targets:
            targets.append(target)
    return targets


# --------------------------------------------------------------------------------------
# 影响面（反向 BFS）
# --------------------------------------------------------------------------------------


def _impact(
    by_id: Dict[str, Dict[str, Any]],
    focus_ids: List[str],
) -> Dict[str, Any]:
    reverse = _build_reverse_index(by_id)
    focus_set: Set[str] = set(focus_ids)

    direct: Set[str] = set()
    for focus_id in focus_ids:
        direct |= reverse.get(focus_id, set())
    direct -= focus_set

    visited: Set[str] = set(focus_set) | direct
    transitive: Set[str] = set()
    frontier = sorted(direct)
    while frontier:
        current = frontier.pop(0)
        for referrer in sorted(reverse.get(current, set())):
            if referrer in visited:
                continue
            visited.add(referrer)
            transitive.add(referrer)
            frontier.append(referrer)

    reachable = focus_set | direct | transitive
    affected_requirements = sorted(
        element_id
        for element_id in reachable
        if by_id.get(element_id, {}).get("kind") == "Requirement"
    )

    return {
        "id": focus_ids[0] if len(focus_ids) == 1 else list(focus_ids),
        "direct": sorted(direct),
        "transitive": sorted(transitive),
        "affected_requirements": affected_requirements,
    }


def _build_reverse_index(
    by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Set[str]]:
    """``target -> 引用它的元素 id 集合``；owner 边为 ``父 -> 子``。"""
    reverse: Dict[str, Set[str]] = {element_id: set() for element_id in by_id}
    for element_id, element in by_id.items():
        properties = element.get("properties")
        if isinstance(properties, dict):
            type_ref = properties.get("typeRef")
            if isinstance(type_ref, str) and type_ref in reverse and type_ref != element_id:
                reverse[type_ref].add(element_id)

        owner = element.get("owner")
        if isinstance(owner, str) and owner in reverse and owner != element_id:
            reverse[owner].add(element_id)

        for relation in element.get("relations") or []:
            if not isinstance(relation, dict):
                continue
            target = relation.get("target")
            if isinstance(target, str) and target in reverse and target != element_id:
                reverse[target].add(element_id)
    return reverse


# --------------------------------------------------------------------------------------
# Markdown 渲染
# --------------------------------------------------------------------------------------


def _render_markdown(
    model: Dict[str, Any],
    matrix: List[Dict[str, Any]],
    gaps: Dict[str, List[str]],
    impact: Optional[Dict[str, Any]],
) -> str:
    status_counts = {status: 0 for status in STATUSES}
    for row in matrix:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1

    lines: List[str] = [
        "# 追溯矩阵",
        "",
        "> 模型：`%s`；需求 %d 条；状态分布：satisfied-and-verified %d / satisfied %d / "
        "verified-only %d / unsatisfied %d。"
        % (
            model.get("package"),
            len(matrix),
            status_counts["satisfied-and-verified"],
            status_counts["satisfied"],
            status_counts["verified-only"],
            status_counts["unsatisfied"],
        ),
        "",
        "| 需求 id | 名称 | 需求摘要 | satisfiedBy | verifiedBy | 状态 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for row in matrix:
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s |"
            % (
                _md_cell(row["requirement"]),
                _md_cell(row["name"] if row["name"] is not None else "—"),
                _md_cell(row["text_short"] if row["text_short"] else "—"),
                _md_ids(row["satisfiedBy"]),
                _md_ids(row["verifiedBy"]),
                row["status"],
            )
        )
    if not matrix:
        lines.append("| — | — | — | — | — | — |")

    lines.extend(["", "## 缺口", ""])
    lines.append("- 未满足（无 satisfiedBy）：%s" % _md_ids(gaps["unsatisfied"]))
    lines.append("- 未被验证的需求：%s" % _md_ids(gaps["unverified_requirement"]))
    lines.append(
        "- 未被验证的功能（ActionDefinition 无 verifies）：%s" % _md_ids(gaps["unverified_action"])
    )

    if impact is not None:
        lines.extend(["", "## 影响面（focus=%s）" % _md_ids(_as_list(impact["id"])), ""])
        lines.append("- 直接引用：%s" % _md_ids(impact["direct"]))
        lines.append("- 传递闭包：%s" % _md_ids(impact["transitive"]))
        lines.append("- 受影响需求：%s" % _md_ids(impact["affected_requirements"]))

    return "\n".join(lines) + "\n"


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _md_ids(ids: Sequence[str]) -> str:
    if not ids:
        return "—"
    return "、".join("`%s`" % _md_cell(item) for item in ids)


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return []


# --------------------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------------------


def _coerce_model(model: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    if isinstance(model, (str, bytes, bytearray)):
        try:
            model = json.loads(model)
        except Exception as exc:  # noqa: BLE001 - 输入来自 LLM，宽进严出
            return None, "输入不是合法 JSON：%s" % exc, "E-INPUT-NOT-JSON"
    if not isinstance(model, dict):
        return None, "IR 顶层必须是 JSON 对象，实际为 %s。" % _type_name(model), "E-ROOT-NOT-OBJECT"
    return model, None, None


def _index_by_id(elements: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for element in elements:
        element_id = element.get("id")
        if isinstance(element_id, str) and element_id not in by_id:
            by_id[element_id] = element
    return by_id


def _normalize_focus(
    focus: Any,
    by_id: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[List[str]], Optional[Dict[str, Any]]]:
    if isinstance(focus, str):
        candidates = [focus]
    elif isinstance(focus, set):
        candidates = sorted(focus, key=str)
    elif isinstance(focus, (list, tuple)):
        candidates = list(focus)
    else:
        return None, _error(
            "E-TRACE-FOCUS-INVALID",
            "`focus` 必须是元素 id 字符串或 id 字符串数组，实际为 %s。" % _type_name(focus),
        )

    if not candidates:
        return None, _error(
            "E-TRACE-FOCUS-INVALID", "`focus` 不能是空数组——至少给一个 id。"
        )

    normalized: List[str] = []
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            return None, _error(
                "E-TRACE-FOCUS-INVALID",
                "`focus` 里的每一项都必须是非空字符串 id，实际为 %s。" % _repr(candidate),
            )
        if candidate not in normalized:
            normalized.append(candidate)

    missing = [item for item in normalized if item not in by_id]
    if missing:
        return None, _error(
            "E-TRACE-FOCUS-NOTFOUND",
            "focus 中的 id 在模型内不存在：%s。" % "、".join("`%s`" % item for item in missing),
        )
    return normalized, None


def _dedupe(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _text_of(element: Dict[str, Any]) -> str:
    properties = element.get("properties")
    if not isinstance(properties, dict):
        return ""
    text = properties.get("text")
    return text if isinstance(text, str) else ""


def _shorten(text: str, limit: int = TEXT_SHORT_LIMIT) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _failure(errors: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "ok": False,
        "matrix": [],
        "gaps": {"unsatisfied": [], "unverified_requirement": [], "unverified_action": []},
        "impact": None,
        "content": None,
        "errors": errors,
    }


def _error(code: str, message: str) -> Dict[str, Any]:
    return {"code": code, "message": message}


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
# CLI：python -m tools.trace <ir.json> [--focus ID] [--fmt json|md]
# --------------------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    from .validator import load_model

    if len(sys.argv) < 2:
        print("用法：python -m tools.trace <ir.json> [--focus ID[,ID...]] [--fmt json|md]")
        raise SystemExit(2)
    options: Dict[str, Any] = {}
    argv = sys.argv[2:]
    i = 0
    while i < len(argv):
        if argv[i] == "--focus" and i + 1 < len(argv):
            raw = argv[i + 1]
            options["focus"] = raw.split(",") if "," in raw else raw
            i += 2
        elif argv[i] == "--fmt" and i + 1 < len(argv):
            options["fmt"] = argv[i + 1]
            i += 2
        else:
            i += 1
    print(json.dumps(traceability(load_model(sys.argv[1]), **options),
                     ensure_ascii=False, indent=2))
