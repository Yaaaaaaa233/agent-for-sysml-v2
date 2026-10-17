"""``sysml_lint`` —— MVP 的 SysML v2 回验底座（轻量语法自查 + 声明抽取 + 元素级比对）。

**为什么是它，而不是现成解析器** —— 见 ``docs/T0-调研结论.md``：

- SysML v2 官方 pilot implementation 是 Java 体系；**本机无 Java 运行时**，无法执行。
- PySysML2 能从 GitHub 装上（Apache-2.0），也能给出带位置的错误，但其语法是
  一个很窄的手写子集：持有关键字表里**没有** ``requirement`` / ``state`` / ``action``，
  连 ``attribute x : Real = 4.0;`` 这种写法都报 ``no viable alternative``——
  而这几样正是 MVP 的核心产物。实测证据见 T0 文档。
- 因此 MVP 选用**内置轻量 lint + 声明抽取 + 元素级比对**做回验；官方解析器与 PySysML2
  的适配统一走 ``tools/sysml_lint.py`` 这一层薄适配（二期替换实现即可）。

能力边界（诚实标注）：本模块**不宣称**等同于官方解析器。它只保证我们从固定模板产出的
那套文本形态自洽、括号闭合、语句终结、声明与 IR 元素一一对应；它能抓住「生成器写坏了」
和「IR 与文本不一致」，抓不住「SysML v2 语义不成立」。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

#: 本 lint 认得的语句起始关键字（本生成器方言 + 常见 SysML v2 记法）
STATEMENT_KEYWORDS = frozenset(
    """
    package part abstract requirement action state attribute in out ref item port connect connection
    import use actor objective subject include message end transition entry then comment doc
    calc constraint interface enum metadata occurrence perform exhibit view viewpoint concern
    satisfy verify bind flow allocation
    """.split()
)

#: 声明抽取正则：(kind, 正则, 分组名 -> 组号)
#: 注意：`package` 用**前瞻**断言 `{`，而不是把它吃进匹配——否则匹配结束位置会落在
#: `{` 之后，作用域计算就找不到这条声明自己的体。
DECLARATION_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("Package", r"\bpackage\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?=\{)"),
    ("PartDefinition", r"\b(?:abstract\s+)?part\s+def\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ("PartUsage", r"\bpart\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)"),
    ("Requirement", r"\brequirement\s+def\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ("ActionDefinition", r"\baction\s+def\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ("StateDefinition", r"\bstate\s+def\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ("State", r"\bstate\s+([A-Za-z_][A-Za-z0-9_]*)\s*;"),
    ("Attribute", r"\battribute\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)"),
)


# --------------------------------------------------------------------------------------
# 语法自查
# --------------------------------------------------------------------------------------


def lint_sysml(text: str) -> Dict[str, Any]:
    """对 SysML v2 文本做轻量语法自查，所有问题都带 ``line`` / ``column``。

    :return: ``{"ok", "errors", "warnings", "stats"}``；每个 error 形如
        ``{"code", "line", "column", "message", "lineText"}``。
    """
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if not isinstance(text, str):
        return {
            "ok": False,
            "errors": [
                {
                    "code": "L000",
                    "line": 0,
                    "column": 0,
                    "message": "输入必须是字符串。",
                    "lineText": "",
                }
            ],
            "warnings": [],
            "stats": {},
        }

    masked, mask_errors = _mask(text)
    line_starts = _line_starts(text)
    source_lines = text.split("\n")

    for code, offset, message in mask_errors:
        errors.append(_at(code, offset, line_starts, source_lines, message))

    # 括号配对
    pairs = {"{": "}", "(": ")", "[": "]"}
    closing = {v: k for k, v in pairs.items()}
    stack: List[Tuple[str, int]] = []
    for index, ch in enumerate(masked):
        if ch in pairs:
            stack.append((ch, index))
        elif ch in closing:
            if not stack:
                errors.append(
                    _at("L005", index, line_starts, source_lines, "多余的闭合符号 `%s`，没有与之配对的 `%s`。" % (ch, closing[ch]))
                )
            elif stack[-1][0] != closing[ch]:
                opener, offset = stack.pop()
                errors.append(
                    _at(
                        "L001",
                        offset,
                        line_starts,
                        source_lines,
                        "括号不匹配：`%s` 被 `%s` 关闭（期望 `%s`）。" % (opener, ch, pairs[opener]),
                    )
                )
            else:
                stack.pop()
    for opener, offset in stack:
        errors.append(
            _at("L001", offset, line_starts, source_lines, "括号未闭合：`%s` 没有对应的 `%s`。" % (opener, pairs[opener]))
        )

    # 语句关键字与终结符
    for line_no, raw_line in enumerate(masked.split("\n")):
        stripped = raw_line.strip()
        if not stripped:
            continue
        column = len(raw_line) - len(raw_line.lstrip()) + 1
        head = re.match(r"[A-Za-z_][A-Za-z0-9_]*", stripped)
        if head is None:
            continue
        word = head.group(0)
        if word not in STATEMENT_KEYWORDS:
            offset = sum(len(l) + 1 for l in masked.split("\n")[:line_no]) + column - 1
            errors.append(
                _at(
                    "L004",
                    offset,
                    line_starts,
                    source_lines,
                    "未知的语句起始关键字 `%s`（不在本 lint 认得的 SysML v2 记法集合内）。" % word,
                )
            )
            continue
        # `doc /* ... */` / `comment /* ... */` 由块注释的 `*/` 收尾，不需要分号
        if line_no < len(source_lines) and source_lines[line_no].rstrip().endswith("*/"):
            continue
        if not stripped.endswith(("{", "}", ";")):
            offset = sum(len(l) + 1 for l in masked.split("\n")[:line_no]) + column - 1
            errors.append(
                _at(
                    "L006",
                    offset,
                    line_starts,
                    source_lines,
                    "语句未以 `;` 或 `{` 终结：`%s`。" % stripped[:60],
                )
            )

    if not re.search(r"\bpackage\s+[A-Za-z_][A-Za-z0-9_]*\s*\{", masked):
        warnings.append(
            {
                "code": "L007",
                "line": 0,
                "column": 0,
                "message": "文本里没有 `package <Name> { ... }` 顶层包裹。",
                "lineText": "",
            }
        )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
            "chars": len(text),
            "errors": len(errors),
            "warnings": len(warnings),
        },
    }


# --------------------------------------------------------------------------------------
# 声明抽取
# --------------------------------------------------------------------------------------


def extract_declarations(text: str) -> Dict[str, Any]:
    """从 SysML v2 文本里抽出声明清单（kind / name / 位置 / typeRef / 所属作用域）。

    在多行文本上做，但用「掩码文本」保证 ``//`` 与 ``/* */`` 注释、字符串字面量里的
    内容不会被误当成声明；掩码等长替换，因此列号仍指向原文。

    每条声明还带 ``scope``（最近的、把它包在体内的外层声明名），用于区分
    「IR 里的 Attribute 元素」与「渲染在 requirement def 体内、由需求阈值生成的
    attribute 语句」——后者不是独立模型元素，元素级比对时要跳过。
    """
    masked, _ = _mask(text)
    line_starts = _line_starts(text)
    source_lines = text.split("\n")

    declarations: List[Dict[str, Any]] = []
    for kind, pattern in DECLARATION_PATTERNS:
        for match in re.finditer(pattern, masked):
            line, column = _locate(match.start(1), line_starts)
            entry: Dict[str, Any] = {
                "kind": kind,
                "name": match.group(1),
                "line": line,
                "column": column,
                "lineText": _line_text(source_lines, line),
                "_start": match.start(),
                "_end": match.end(),
            }
            if kind == "PartUsage":
                entry["typeRef"] = match.group(2)
            declarations.append(entry)

    # State 声明必须排除 `state def X`
    declarations = [
        d
        for d in declarations
        if not (d["kind"] == "State" and _is_definition_name(masked, d, "state"))
    ]
    declarations.sort(key=lambda d: (d["_start"], d["_end"]))

    _annotate_scopes(masked, declarations)

    for declaration in declarations:
        declaration.pop("_start", None)
        declaration.pop("_end", None)

    return {
        "ok": True,
        "count": len(declarations),
        "declarations": declarations,
        "byKind": _count_by_kind(declarations),
    }


def _annotate_scopes(masked: str, declarations: List[Dict[str, Any]]) -> None:
    """给每条声明算出它所在的最内层块，并标注该块的开括号属于哪条声明。"""
    # 括号配对
    stack: List[int] = []
    open_to_close: Dict[int, int] = {}
    for index, ch in enumerate(masked):
        if ch == "{":
            stack.append(index)
        elif ch == "}" and stack:
            open_to_close[stack.pop()] = index

    # 每条声明自己的体：签名之后的**第一个非空白字符**是 `{` 则有体，否则没有。
    # （不能「往后找第一个 `{`」——那会把兄弟元素的体错认成自己的。）
    for declaration in declarations:
        cursor = declaration["_end"]
        limit = len(masked)
        while cursor < limit and masked[cursor] in " \t\r\n":
            cursor += 1
        declaration["braceIndex"] = (
            cursor if cursor < limit and masked[cursor] == "{" else None
        )

    # 计算每条声明的 scope
    for declaration in declarations:
        position = declaration["_start"]
        best: Optional[Dict[str, Any]] = None
        best_open = -1
        for candidate in declarations:
            if candidate is declaration:
                continue
            open_index = candidate.get("braceIndex")
            if open_index is None:
                continue
            close_index = open_to_close.get(open_index)
            if close_index is None:
                continue
            if open_index < position < close_index and open_index > best_open:
                best = candidate
                best_open = open_index
        declaration["scope"] = best["name"] if best is not None else "package"
        declaration["scopeKind"] = best["kind"] if best is not None else "Package"


def _is_definition_name(masked: str, declaration: Dict[str, Any], keyword: str) -> bool:
    needle = "%s def %s" % (keyword, declaration["name"])
    return needle in masked


# --------------------------------------------------------------------------------------
# 元素级比对（方案 2.3 第 4 步：解析成功后再与原始 IR 做元素级比对）
# --------------------------------------------------------------------------------------


def roundtrip_check(model: Any, text: str) -> Dict[str, Any]:
    """把 IR 与生成文本做元素级比对。

    比对口径：对每个 IR 元素，文本里必须有一条 ``kind`` 与 ``name`` 都相同的声明；
    反之文本里的每条声明（除 ``Package`` 与 ``State``）都必须在 IR 中有对应元素。
    PartUsage 额外比对 ``typeRef``。

    :return: ``{"ok", "missing", "extra", "mismatched", "lint", "counts"}``
    """
    if isinstance(model, (str, bytes, bytearray)):
        try:
            model = json.loads(model)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": "IR 不是合法 JSON：%s" % exc,
                "missing": [],
                "extra": [],
                "mismatched": [],
            }

    lint = lint_sysml(text)
    extraction = extract_declarations(text)
    declarations = extraction["declarations"]

    elements = [e for e in ((model or {}).get("elements") or []) if isinstance(e, dict)]

    text_index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for declaration in declarations:
        if declaration["kind"] in ("Package", "State"):
            continue
        # 渲染在 requirement def 体内、由需求阈值生成的 attribute 语句
        # 不是独立模型元素（IR 里没有对应的 Attribute 元素），比对时跳过。
        if declaration["kind"] == "Attribute" and declaration.get("scopeKind") == "Requirement":
            continue
        text_index.setdefault((declaration["kind"], declaration["name"]), declaration)

    ir_index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    name_by_id: Dict[str, str] = {}
    for element in elements:
        kind = element.get("kind")
        name = element.get("name")
        if isinstance(element.get("id"), str) and isinstance(name, str):
            name_by_id[element["id"]] = name
        if isinstance(kind, str) and isinstance(name, str):
            ir_index.setdefault((kind, name), element)

    missing: List[Dict[str, Any]] = []
    mismatched: List[Dict[str, Any]] = []
    for key, element in sorted(ir_index.items()):
        declaration = text_index.get(key)
        if declaration is None:
            missing.append({"kind": key[0], "name": key[1], "id": element.get("id")})
            continue
        if key[0] == "PartUsage":
            # 文本里写的是被引用元素的 name；IR 里存的是它的 id，先解析再比。
            ir_type_id = (element.get("properties") or {}).get("typeRef")
            ir_type = name_by_id.get(ir_type_id, ir_type_id)
            if ir_type != declaration.get("typeRef"):
                mismatched.append(
                    {
                        "kind": key[0],
                        "name": key[1],
                        "id": element.get("id"),
                        "field": "typeRef",
                        "ir": ir_type,
                        "irId": ir_type_id,
                        "text": declaration.get("typeRef"),
                        "line": declaration["line"],
                    }
                )

    extra: List[Dict[str, Any]] = []
    for key, declaration in sorted(text_index.items()):
        if key not in ir_index:
            extra.append(
                {
                    "kind": key[0],
                    "name": key[1],
                    "line": declaration["line"],
                    "column": declaration["column"],
                }
            )

    return {
        "ok": lint["ok"] and not missing and not extra and not mismatched,
        "lint": lint,
        "missing": missing,
        "extra": extra,
        "mismatched": mismatched,
        "counts": {
            "irElements": len(elements),
            "textDeclarations": extraction["count"],
            "matched": len(ir_index) - len(missing),
            "missing": len(missing),
            "extra": len(extra),
            "mismatched": len(mismatched),
            "lintErrors": len(lint["errors"]),
        },
        "declarationsByKind": extraction["byKind"],
    }


# --------------------------------------------------------------------------------------
# 内部工具
# --------------------------------------------------------------------------------------


def _mask(text: str) -> Tuple[str, List[Tuple[str, int, str]]]:
    """把注释与字符串内容替换成空格（等长），返回 (掩码文本, 错误列表)。"""
    out = list(text)
    errors: List[Tuple[str, int, str]] = []
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        if ch == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] != "\n":
                out[index] = " "
                index += 1
        elif ch == "/" and index + 1 < length and text[index + 1] == "*":
            start = index
            out[index] = " "
            out[index + 1] = " "
            index += 2
            closed = False
            while index < length:
                if text[index] == "*" and index + 1 < length and text[index + 1] == "/":
                    out[index] = " "
                    out[index + 1] = " "
                    index += 2
                    closed = True
                    break
                if text[index] != "\n":
                    out[index] = " "
                index += 1
            if not closed:
                errors.append(("L002", start, "块注释 `/*` 未闭合。"))
        elif ch == '"':
            start = index
            out[index] = " "
            index += 1
            closed = False
            while index < length:
                if text[index] == "\\" and index + 1 < length:
                    out[index] = " "
                    out[index + 1] = " "
                    index += 2
                    continue
                if text[index] == '"':
                    out[index] = " "
                    index += 1
                    closed = True
                    break
                if text[index] != "\n":
                    out[index] = " "
                index += 1
            if not closed:
                errors.append(("L003", start, "字符串字面量未闭合（缺收尾的双引号）。"))
        else:
            index += 1
    return "".join(out), errors


def _line_starts(text: str) -> List[int]:
    starts = [0]
    for index, ch in enumerate(text):
        if ch == "\n":
            starts.append(index + 1)
    return starts


def _locate(offset: int, line_starts: List[int]) -> Tuple[int, int]:
    low, high = 0, len(line_starts) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if line_starts[mid] <= offset:
            low = mid
        else:
            high = mid - 1
    return low + 1, offset - line_starts[low] + 1


def _line_text(source_lines: List[str], line: int) -> str:
    if 1 <= line <= len(source_lines):
        return source_lines[line - 1]
    return ""


def _at(
    code: str,
    offset: int,
    line_starts: List[int],
    source_lines: List[str],
    message: str,
) -> Dict[str, Any]:
    line, column = _locate(offset, line_starts)
    return {
        "code": code,
        "line": line,
        "column": column,
        "message": message,
        "lineText": _line_text(source_lines, line),
    }


def _count_by_kind(declarations: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for declaration in declarations:
        counts[declaration["kind"]] = counts.get(declaration["kind"], 0) + 1
    return counts


def verify(model: Any, text: str) -> Dict[str, Any]:
    """回验一站式入口：lint + 元素级比对。"""
    return roundtrip_check(model, text)


# --------------------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) < 2:
        print("用法：python -m tools.sysml_lint <model.sysml> [ir.json]")
        raise SystemExit(2)
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        content = handle.read()
    if len(sys.argv) >= 3:
        with open(sys.argv[2], "r", encoding="utf-8") as handle:
            outcome = roundtrip_check(json.load(handle), content)
    else:
        outcome = lint_sysml(content)
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    raise SystemExit(0 if outcome.get("ok") else 1)
