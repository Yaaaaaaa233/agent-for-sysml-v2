"""``query_model`` —— 查模型现状。

技术方案 5.3 把「先查现状」定为每一步的固定动作：动手改模型之前，先确认
「是否已有同类元素」「id 与命名是否被占用」「某元素被谁引用」。

MVP 支持四种查询（方案 9.1 的 T2）：

1. 按关键字 / kind 查元素
2. 查某 id 的引用者（谁引用了它）
3. 查重名（同 owner 下 name 重复、id 重复）
4. 列未被满足的需求（没有 satisfiedBy 关系）

纯函数：入参与返回值都是 JSON 可序列化结构；不修改传入的模型。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .validator import KINDS

DEFAULT_LIMIT = 200


def query_model(
    model: Any,
    *,
    keyword: Optional[str] = None,
    kind: Optional[str] = None,
    referrers_of: Optional[str] = None,
    duplicates: bool = False,
    unsatisfied_requirements: bool = False,
    details: bool = False,
    limit: int = DEFAULT_LIMIT,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """在 IR JSON 上做只读查询。

    :param model: IR JSON（dict 或 JSON 字符串）
    :param keyword: 关键字；大小写不敏感地匹配 id / name / owner / kind 及 properties 文本
    :param kind: 按 kind 过滤（受控枚举之一）
    :param referrers_of: 查「谁引用了这个 id」（含 relations 反向引用与 PartUsage.typeRef）
    :param duplicates: True 时汇报 id 重复与同 owner 下 name 重复
    :param unsatisfied_requirements: True 时列出没有 satisfiedBy 关系的需求
    :param details: True 时一并返回命中的完整元素
    :param limit: 结果条数上限（默认 200）
    :param query: ``keyword`` 的别名（MCP 客户端常把入参叫 query）
    :return: ``{"ok", "mode", "count", "results", ...}``
    """
    if keyword is None and query is not None:
        keyword = query

    model, error = _coerce(model)
    if error:
        return {"ok": False, "mode": "error", "count": 0, "results": [], "error": error}

    elements: List[Dict[str, Any]] = [
        e for e in (model.get("elements") or []) if isinstance(e, dict)
    ]
    package = model.get("package")

    if referrers_of:
        return _referrers(elements, referrers_of, limit, details)
    if duplicates:
        return _duplicates(elements, limit)
    if unsatisfied_requirements:
        return _unsatisfied(elements, limit, details)

    return _search(elements, package, keyword, kind, limit, details)


# --------------------------------------------------------------------------------------


def _coerce(model: Any):
    if isinstance(model, (str, bytes, bytearray)):
        try:
            return json.loads(model), None
        except Exception as exc:  # noqa: BLE001
            return None, "输入不是合法 JSON：%s" % exc
    if not isinstance(model, dict):
        return None, "IR 顶层必须是 JSON 对象，实际为 %s。" % type(model).__name__
    return model, None


def _brief(element: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": element.get("id"),
        "kind": element.get("kind"),
        "name": element.get("name"),
        "owner": element.get("owner"),
    }


def _search(
    elements: List[Dict[str, Any]],
    package: Any,
    keyword: Optional[str],
    kind: Optional[str],
    limit: int,
    details: bool,
) -> Dict[str, Any]:
    if kind is not None and kind not in KINDS:
        return {
            "ok": False,
            "mode": "elements",
            "count": 0,
            "results": [],
            "error": "kind 必须是受控枚举之一：%s。" % "、".join(KINDS),
            "allowedKinds": list(KINDS),
        }

    needle = keyword.casefold() if isinstance(keyword, str) and keyword else None
    hits: List[Dict[str, Any]] = []

    for element in sorted(elements, key=lambda e: str(e.get("id"))):
        if kind is not None and element.get("kind") != kind:
            continue
        matched: List[str] = []
        if needle is not None:
            for field in ("id", "name", "owner", "kind"):
                value = element.get(field)
                if isinstance(value, str) and needle in value.casefold():
                    matched.append(field)
            props = element.get("properties")
            if isinstance(props, dict) and _props_match(props, needle):
                matched.append("properties")
            relations = element.get("relations")
            if isinstance(relations, list) and _props_match({"relations": relations}, needle):
                matched.append("relations")
            if not matched:
                continue
        entry = _brief(element)
        if matched:
            entry["matched"] = matched
        if details:
            entry["element"] = element
        hits.append(entry)

    return {
        "ok": True,
        "mode": "elements",
        "package": package,
        "keyword": keyword,
        "kind": kind,
        "count": len(hits),
        "truncated": len(hits) > limit,
        "results": hits[:limit],
    }


def _props_match(props: Dict[str, Any], needle: str) -> bool:
    for value in _flatten(props):
        if needle in value.casefold():
            return True
    return False


def _flatten(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            out.extend(_flatten(item))
        return out
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            out.append(str(key))
            out.extend(_flatten(item))
        return out
    return []


def _referrers(
    elements: List[Dict[str, Any]],
    target: str,
    limit: int,
    details: bool,
) -> Dict[str, Any]:
    exists = any(e.get("id") == target for e in elements)
    referrers: List[Dict[str, Any]] = []

    for element in sorted(elements, key=lambda e: str(e.get("id"))):
        if element.get("id") == target:
            continue
        props = element.get("properties")
        if isinstance(props, dict) and props.get("typeRef") == target:
            referrers.append(
                {
                    "id": element.get("id"),
                    "kind": element.get("kind"),
                    "name": element.get("name"),
                    "via": "properties.typeRef",
                    "rationale": None,
                }
            )
        for relation in element.get("relations") or []:
            if not isinstance(relation, dict) or relation.get("target") != target:
                continue
            referrers.append(
                {
                    "id": element.get("id"),
                    "kind": element.get("kind"),
                    "name": element.get("name"),
                    "via": "relations.%s" % relation.get("type"),
                    "rationale": relation.get("rationale"),
                }
            )

    results = referrers if details else [r for r in referrers]
    return {
        "ok": True,
        "mode": "referrers",
        "target": target,
        "targetExists": exists,
        "count": len(results),
        "truncated": len(results) > limit,
        "results": results[:limit],
    }


def _duplicates(elements: List[Dict[str, Any]], limit: int) -> Dict[str, Any]:
    by_id: Dict[str, int] = {}
    for element in elements:
        element_id = element.get("id")
        if isinstance(element_id, str):
            by_id[element_id] = by_id.get(element_id, 0) + 1
    duplicate_ids = sorted(k for k, v in by_id.items() if v > 1)

    by_name: Dict[Any, List[str]] = {}
    for element in elements:
        owner = element.get("owner")
        name = element.get("name")
        if isinstance(owner, str) and isinstance(name, str):
            by_name.setdefault((owner, name), []).append(str(element.get("id")))

    duplicate_names = [
        {"owner": owner, "name": name, "ids": sorted(ids)}
        for (owner, name), ids in sorted(by_name.items())
        if len(ids) > 1
    ]

    results = [
        {"type": "id", "value": element_id} for element_id in duplicate_ids
    ] + [
        {"type": "name", "owner": item["owner"], "value": item["name"], "ids": item["ids"]}
        for item in duplicate_names
    ]

    return {
        "ok": True,
        "mode": "duplicates",
        "count": len(results),
        "truncated": len(results) > limit,
        "duplicateIds": duplicate_ids,
        "duplicateNames": duplicate_names,
        "results": results[:limit],
    }


def _unsatisfied(
    elements: List[Dict[str, Any]],
    limit: int,
    details: bool,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for element in sorted(elements, key=lambda e: str(e.get("id"))):
        if element.get("kind") != "Requirement":
            continue
        relation_types = {
            r.get("type") for r in (element.get("relations") or []) if isinstance(r, dict)
        }
        if "satisfiedBy" in relation_types:
            continue
        entry = _brief(element)
        props = element.get("properties")
        if isinstance(props, dict):
            entry["text"] = props.get("text")
        if details:
            entry["element"] = element
        results.append(entry)

    return {
        "ok": True,
        "mode": "unsatisfiedRequirements",
        "count": len(results),
        "truncated": len(results) > limit,
        "results": results[:limit],
    }


# --------------------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    from .validator import load_model

    if len(sys.argv) < 2:
        print("用法：python -m tools.query <ir.json> [--keyword K] [--kind KIND] "
              "[--referrers-of ID] [--duplicates] [--unsatisfied]")
        raise SystemExit(2)
    run = load_model(sys.argv[1])
    options: Dict[str, Any] = {}
    argv = sys.argv[2:]
    i = 0
    while i < len(argv):
        flag = argv[i]
        if flag == "--keyword":
            options["keyword"] = argv[i + 1]
            i += 2
        elif flag == "--kind":
            options["kind"] = argv[i + 1]
            i += 2
        elif flag == "--referrers-of":
            options["referrers_of"] = argv[i + 1]
            i += 2
        elif flag == "--duplicates":
            options["duplicates"] = True
            i += 1
        elif flag == "--unsatisfied":
            options["unsatisfied_requirements"] = True
            i += 1
        elif flag == "--details":
            options["details"] = True
            i += 1
        else:
            i += 1
    print(json.dumps(query_model(run, **options), ensure_ascii=False, indent=2))
