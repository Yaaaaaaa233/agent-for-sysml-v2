"""``query_model`` —— 查模型现状。

技术方案 5.3 把「先查现状」定为每一步的固定动作：动手改模型之前，先确认
「是否已有同类元素」「id 与命名是否被占用」「某元素被谁引用」。

MVP 支持四种查询（方案 9.1 的 T2）：

1. 按关键字 / kind 查元素
2. 查某 id 的引用者（谁引用了它）
3. 查重名（同 owner 下 name 重复、id 重复）
4. 列未被满足的需求（没有 satisfiedBy 关系）

输入有两种给法（**二选一**）：直接给 ``model``（IR JSON 对象/字符串），或给
``path``（**服务端本机**的 IR JSON 文件路径）。后者来自试用反馈：客户端每次都把
整份模型塞进请求很啰嗦。注意 ``path`` 只在服务端本机可用——云端部署应上传内容
本身，而不是路径（容器里没有你这台机器上的文件）。

``path`` 的目录边界由环境变量 ``SYSML_QUERY_ROOT`` 控制：**云端 / streamable-http
部署应设置它**来限制数据目录，设置后 ``path`` 解析（含符号链接）必须落在该根目录
之下（含根本身），否则报 ``E-QUERY-PATH-OUTSIDE-ROOT``；不设置时保持原有的「不限制」
行为（本地脚本/单机使用）。

``referrers_of`` 查的是**引用边**，口径见 ``query_model`` 的文档：``relations[].target``、
``properties.typeRef``、``Constraint.properties.parameters``、``Connection`` 的
``properties.sourceRef`` / ``targetRef``；``owner`` 归属链**不算**引用边。

纯函数：入参与返回值都是 JSON 可序列化结构；不修改传入的模型。
（按 ``path`` 读文件是唯一的 I/O，且只读。）
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .validator import KINDS, load_model

DEFAULT_LIMIT = 200

#: 可选的查询根目录环境变量：设置后 ``path`` 只能读该目录（含子目录）下的文件
QUERY_ROOT_ENV = "SYSML_QUERY_ROOT"


def query_model(
    model: Any = None,
    *,
    path: Optional[str] = None,
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

    :param model: IR JSON（dict 或 JSON 字符串）；与 ``path`` 二选一
    :param path: 服务端本地 IR JSON 文件路径；与 ``model`` 二选一。
        仅服务端本机可用；云端 / streamable-http 部署应上传内容而非路径，
        并设置环境变量 ``SYSML_QUERY_ROOT`` 限制数据目录。设置后路径（解析符号链接后）
        必须落在该根目录之下（含根本身），否则报 ``E-QUERY-PATH-OUTSIDE-ROOT``
    :param keyword: 关键字；大小写不敏感地匹配 id / name / owner / kind 及 properties 文本
    :param kind: 按 kind 过滤（受控枚举之一）
    :param referrers_of: 查「谁引用了这个 id」。引用边口径：``relations[].target``、
        ``properties.typeRef``、``Constraint.properties.parameters``（元素 id 数组）、
        ``Connection.properties.sourceRef`` / ``targetRef``；``owner`` 归属链不算引用边
    :param duplicates: True 时汇报 id 重复与同 owner 下 name 重复
    :param unsatisfied_requirements: True 时列出没有 satisfiedBy 关系的需求
    :param details: True 时一并返回命中的完整元素
    :param limit: 结果条数上限（默认 200）
    :param query: ``keyword`` 的别名（MCP 客户端常把入参叫 query）
    :return: ``{"ok", "mode", "count", "results", ...}``
    """
    if keyword is None and query is not None:
        keyword = query

    model, error = _resolve_source(model, path)
    if error:
        return _input_error(error, path)

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


def _input_error(error: str, path: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": False,
        "mode": "error",
        "count": 0,
        "results": [],
        "error": error,
    }
    if path is not None:
        payload["path"] = path
    return payload


def _resolve_source(model: Any, path: Optional[str]) -> Tuple[Any, Optional[str]]:
    """把 ``model`` / ``path`` 归一成一个模型对象；不满足二选一约束时报错。

    ``path`` 只接受字符串；读取失败（不存在 / 不是 UTF-8 / 不是 JSON / 顶层不是
    对象）一律转成错误文本，**不向调用方抛栈**——MCP 客户端要的是可读的原因。
    """
    if path is not None:
        if model is not None:
            return None, (
                "`model` 与 `path` 只能二选一：直接给 IR JSON（model），"
                "或给服务端本地文件路径（path）。"
            )
        if isinstance(path, os.PathLike):
            path = os.fspath(path)
        if not isinstance(path, str) or not path.strip():
            return None, "`path` 必须是非空字符串（服务端本地 IR JSON 文件路径），实际为 %s。" % (
                _type_name(path)
            )
        candidate: Any = None
        try:
            candidate = Path(path).expanduser()
        except Exception as exc:  # noqa: BLE001 - 路径本身就是外部输入
            return None, "无法解析 path `%s`：%s。" % (path, exc)
        root_error = _check_query_root(candidate)
        if root_error is not None:
            return None, root_error
        try:
            loaded = load_model(candidate)
        except FileNotFoundError:
            return None, "path 指向的文件不存在：`%s`。" % _display_path(path, candidate)
        except IsADirectoryError:
            return None, "path 指向的是目录，不是 IR JSON 文件：`%s`。" % _display_path(
                path, candidate
            )
        except UnicodeDecodeError as exc:
            return None, "path 指向的文件不是 UTF-8 文本：`%s`（%s）。" % (
                _display_path(path, candidate),
                exc,
            )
        except OSError as exc:
            return None, "读取 path `%s` 失败：%s。" % (_display_path(path, candidate), exc)
        except ValueError as exc:
            return None, "path `%s` 不是合法 JSON：%s。" % (_display_path(path, candidate), exc)
        except Exception as exc:  # noqa: BLE001 - 输入来自外部文件，必须宽进严出
            return None, "读取 path `%s` 失败：%s。" % (_display_path(path, candidate), exc)

        if not isinstance(loaded, dict):
            return None, "path `%s` 的顶层必须是 JSON 对象（IR 模型），实际为 %s。" % (
                _display_path(path, candidate),
                _type_name(loaded),
            )
        return loaded, None

    if model is None:
        return None, (
            "缺少输入：必须提供 `model`（IR JSON）或 `path`（服务端本地 IR JSON 文件路径）之一。"
        )
    return _coerce(model)


def _check_query_root(candidate: Any) -> Optional[str]:
    """``SYSML_QUERY_ROOT`` 的目录边界检查；未设置时返回 None（不限制）。

    比较前**两端都先解析符号链接**（``Path.resolve``）：根目录里的软链接若指向根外，
    解析后落在根外 → 拒绝，避免用一条软链接绕过目录限制。根本身允许（``relative_to``
    得到 ``.``），只是它通常是个目录，后面 ``load_model`` 会按「指向目录」报错。
    """
    raw = os.environ.get(QUERY_ROOT_ENV)
    if raw is None or not str(raw).strip():
        return None
    root_text = str(raw).strip()
    try:
        root = Path(root_text).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return "环境变量 %s=`%s` 无法解析为目录：%s（E-QUERY-PATH-ROOT-INVALID）。" % (
            QUERY_ROOT_ENV,
            root_text,
            exc,
        )
    try:
        resolved = Path(candidate).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return "path `%s` 无法解析（可能是符号链接环）：%s（E-QUERY-PATH-OUTSIDE-ROOT）。" % (
            candidate,
            exc,
        )
    try:
        resolved.relative_to(root)
    except ValueError:
        return (
            "path `%s` 解析后是 `%s`，不在 %s=`%s` 允许的目录之下，拒绝读取"
            "（E-QUERY-PATH-OUTSIDE-ROOT）。"
        ) % (candidate, resolved, QUERY_ROOT_ENV, root)
    return None


def _display_path(raw: str, candidate: Any) -> str:
    return str(candidate) if candidate is not None else raw


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


def _referrer_edges(element: Dict[str, Any], target: str) -> List[Tuple[str, Any]]:
    """列出该元素指向 ``target`` 的引用边：``(via, rationale)``。

    口径（与 ``query_model`` 文档一致）：

    - ``relations[].target`` → ``relations.<type>``；
    - ``properties.typeRef`` → ``properties.typeRef``（PartUsage 指向 PartDefinition）；
    - ``Constraint.properties.parameters`` → ``properties.parameters``（元素 id 数组）；
    - ``Connection.properties.sourceRef`` / ``targetRef`` → 同名 ``via``。

    ``owner`` 归属链**不算**引用边：父子归属不等于「引用了它」，
    否则每个元素的 owner 都会把整棵父链算成引用方，追溯结果会被噪声淹没。
    """
    edges: List[Tuple[str, Any]] = []
    props = element.get("properties")
    if isinstance(props, dict):
        if props.get("typeRef") == target:
            edges.append(("properties.typeRef", None))
        parameters = props.get("parameters")
        if isinstance(parameters, list) and target in parameters:
            edges.append(("properties.parameters", None))
        for field in ("sourceRef", "targetRef"):
            if props.get(field) == target:
                edges.append(("properties.%s" % field, None))
    for relation in element.get("relations") or []:
        if not isinstance(relation, dict) or relation.get("target") != target:
            continue
        edges.append(("relations.%s" % relation.get("type"), relation.get("rationale")))
    return edges


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
        for via, rationale in _referrer_edges(element, target):
            referrers.append(
                {
                    "id": element.get("id"),
                    "kind": element.get("kind"),
                    "name": element.get("name"),
                    "via": via,
                    "rationale": rationale,
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
