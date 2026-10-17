"""``sysml_lint`` —— MVP 的 SysML v2 回验底座（轻量语法自查 + 声明抽取 + 元素级比对）。

**为什么是它，而不是现成解析器** —— 见 ``docs/T0-调研结论.md``：

- SysML v2 官方 pilot implementation 是 Java 体系；T0 调研时**本机无 Java 运行时**，无法执行。
- PySysML2 能从 GitHub 装上（Apache-2.0），也能给出带位置的错误，但其语法是
  一个很窄的手写子集：持有关键字表里**没有** ``requirement`` / ``state`` / ``action``，
  连 ``attribute x : Real = 4.0;`` 这种写法都报 ``no viable alternative``——
  而这几样正是 MVP 的核心产物。实测证据见 T0 文档。
- 2026-10-17 起，仓库内 ``docs/probe-official-parser/`` 由并行 spike 提供了官方
  Pilot Implementation 探测后端（入口 ``tools/official_parser.py``）。官方解析器的结果
  单独走那一层，**不混进本模块**，也不把 lint 通过冒充成官方通过。
- 因此 MVP 仍选用**内置轻量 lint + 声明抽取 + 元素级比对**做日常回验；官方解析器与
  PySysML2 的适配统一走薄适配层（二期替换实现即可）。

能力边界（诚实标注）：本模块**不宣称**等同于官方解析器。它只保证我们从固定模板产出的
那套文本形态自洽、括号闭合、语句终结、声明与 IR 元素一一对应；它能抓住「生成器写坏了」
和「IR 与文本不一致」，抓不住「SysML v2 语义不成立」。

v1 增补（2026-10-17）后额外支持解析/自查：

- ``Attribute`` 的单位后缀 ``[unit]`` 与 ``PartUsage`` 的多重度后缀 ``[n]``；
- 官方状态机记法 ``entry; then <state>;`` 与
  ``transition <name> first ... [if (...)] then ...;``（trigger 在上一行 ``// trigger:``）；
- ``constraint def`` 及其体内结构化注释 ``// expression:`` / ``// parameters:``；
- ``// Connection <id> flowKind=... name=<name> [description: ...]`` +
  ``connect <src> to <tgt>;`` 成对结构（``extract_connections``；格式错误 L008 /
  缺 connect 语句 L009 / 迁移形态错误 L010）；
- 生成器固定输出的 ``private import ScalarValues::*;`` / ``private import SI::*;``
  （语句关键字含 ``private`` / ``public``，不把 import 行误判为未知语句）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

#: 本 lint 认得的语句起始关键字（本生成器方言 + 常见 SysML v2 记法）
STATEMENT_KEYWORDS = frozenset(
    """
    package part abstract requirement action state attribute in out ref item port connect connection
    import private public protected use actor objective subject include message end transition entry then comment doc
    calc constraint interface enum metadata occurrence perform exhibit view viewpoint concern
    satisfy verify bind flow allocation accept if
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
    ("Constraint", r"\bconstraint\s+def\s+([A-Za-z_][A-Za-z0-9_]*)"),
)

#: 语句后缀 `[unit]` / `[n]`：位于 `;` 或 `{` 之前（可带行尾注释）
BRACKET_SUFFIX_RE = re.compile(r"\[([^\[\]\r\n]+)\]\s*(?:;|\{)\s*(?://.*)?$")

#: 结构化注释：Constraint 的 expression / parameters（与 generator 的渲染逐一对应）
CONSTRAINT_EXPRESSION_RE = re.compile(r"^//\s*expression:\s*(.*)$")
CONSTRAINT_PARAMETERS_RE = re.compile(r"^//\s*parameters:\s*(.*)$")

#: 结构化注释：Connection 的
#: `// Connection <id> flowKind=<flowKind> [name=<name>] [description: ...]`
#: （``name=`` 是 v2 逆解析新增：``connect`` 语句本身没有名字位置，不落进注释就无法还原 IR）
CONNECTION_ANNOTATION_RE = re.compile(
    r"^//\s*Connection\s+([A-Za-z_][A-Za-z0-9_-]*)\s+flowKind=([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+name=([A-Za-z_][A-Za-z0-9_]*))?"
    r"(?:\s+description:\s*(.*))?$"
)

#: `connect <srcName> to <tgtName>;`
CONNECT_STATEMENT_RE = re.compile(
    r"^connect\s+([A-Za-z_][A-Za-z0-9_]*)\s+to\s+([A-Za-z_][A-Za-z0-9_]*)\s*;$"
)

#: 状态机初始态：官方记法 `entry; then <State>;`
INITIAL_STATEMENT_RE = re.compile(
    r"^entry\s*;\s*then\s+([A-Za-z_][A-Za-z0-9_]*)\s*;$"
)

#: 状态迁移：`transition <name> first <from> [if (<guard>)] then <to>;`
TRANSITION_STATEMENT_RE = re.compile(
    r"^transition\s+([A-Za-z_][A-Za-z0-9_]*)\s+first\s+([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+if\s*\((.*)\))?\s+then\s+([A-Za-z_][A-Za-z0-9_]*)\s*;$"
)

#: trigger 以结构化注释承载（guard 在 transition 语句里，见 渲染约定.md §2.5）
TRIGGER_COMMENT_RE = re.compile(r"^//\s*trigger:\s*(.*)$")


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

    # 结构化注释（Connection）：格式必须可逆解析回 IR
    connection_scan = extract_connections(text)
    for entry in connection_scan["malformed"]:
        errors.append(
            {
                "code": "L008",
                "line": entry["line"],
                "column": entry["column"],
                "message": entry["message"],
                "lineText": entry["lineText"],
            }
        )
    for entry in connection_scan["incomplete"]:
        errors.append(
            {
                "code": "L009",
                "line": entry["line"],
                "column": entry["column"],
                "message": "`// Connection ...` 结构化注释下方必须紧跟一条 "
                "`connect <src> to <tgt>;` 语句（回验靠这一对还原 IR）。",
                "lineText": entry["lineText"],
            }
        )

    # 状态迁移必须是本约定的单行形态（官方 `transition <name> first ... then ...;`）
    masked_lines = masked.split("\n")
    for line_no, raw in enumerate(masked_lines):
        stripped = raw.strip()
        if not stripped.startswith("transition"):
            continue
        if TRANSITION_STATEMENT_RE.match(stripped) is None:
            column = len(raw) - len(raw.lstrip()) + 1
            errors.append(
                {
                    "code": "L010",
                    "line": line_no + 1,
                    "column": column,
                    "message": "状态迁移必须是单行 `transition <name> first <from> "
                    "[if (<guard>)] then <to>;`（trigger 请用上一行 `// trigger: ...`）。",
                    "lineText": _line_text(source_lines, line_no + 1),
                }
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

    新语法相关的附加字段：``Attribute.unit`` / ``PartUsage.multiplicity`` 来自
    ``[unit]`` / ``[n]`` 后缀；``Constraint.expression`` 与 ``Constraint.parameters``
    来自体内结构化注释；``StateDefinition.initial`` / ``StateDefinition.transitions``
    来自 ``entry; then ...;`` 与 ``transition ... first ... then ...;``（trigger 在
    上一行 ``// trigger:``）。
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

    open_to_close = _annotate_scopes(masked, declarations)
    _annotate_structured_comments(
        declarations, open_to_close, source_lines, line_starts
    )

    for declaration in declarations:
        declaration.pop("_start", None)
        declaration.pop("_end", None)

    return {
        "ok": True,
        "count": len(declarations),
        "declarations": declarations,
        "byKind": _count_by_kind(declarations),
    }


def _annotate_structured_comments(
    declarations: List[Dict[str, Any]],
    open_to_close: Dict[int, int],
    source_lines: List[str],
    line_starts: List[int],
) -> None:
    """补两类别名信息，供逆解析与元素级比对使用。

    - ``Constraint``：从体内结构化注释取 ``expression`` / ``parameters``；
    - ``Attribute`` / ``PartUsage``：从语句后缀取 ``[unit]`` / ``[n]``。
    """
    for declaration in declarations:
        kind = declaration["kind"]

        if kind in ("Attribute", "PartUsage"):
            match = BRACKET_SUFFIX_RE.search(declaration.get("lineText", ""))
            if match:
                key = "unit" if kind == "Attribute" else "multiplicity"
                declaration[key] = match.group(1).strip()
            continue

        if kind not in ("Constraint", "StateDefinition"):
            continue

        brace_index = declaration.get("braceIndex")
        close_index = open_to_close.get(brace_index) if brace_index is not None else None
        if close_index is None:
            continue
        close_line, _ = _locate(close_index, line_starts)
        # 声明所在行之后、闭合行之前，就是这个元素的体
        body = source_lines[declaration["line"] : close_line - 1]

        if kind == "Constraint":
            for raw in body:
                stripped = raw.strip()
                match = CONSTRAINT_EXPRESSION_RE.match(stripped)
                if match and "expression" not in declaration:
                    declaration["expression"] = match.group(1).strip()
                    continue
                match = CONSTRAINT_PARAMETERS_RE.match(stripped)
                if match and "parameters" not in declaration:
                    declaration["parameters"] = [
                        item.strip() for item in match.group(1).split(",") if item.strip()
                    ]
            continue

        # StateDefinition：初始态 + 迁移（trigger 来自结构化注释，guard 来自语句）
        transitions: List[Dict[str, Any]] = []
        pending_trigger: Optional[str] = None
        for raw in body:
            stripped = raw.strip()
            match = TRIGGER_COMMENT_RE.match(stripped)
            if match:
                pending_trigger = match.group(1).strip()
                continue
            match = INITIAL_STATEMENT_RE.match(stripped)
            if match:
                declaration["initial"] = match.group(1)
                continue
            match = TRANSITION_STATEMENT_RE.match(stripped)
            if match:
                transitions.append(
                    {
                        "name": match.group(1),
                        "from": match.group(2),
                        "to": match.group(4),
                        "guard": (match.group(3) or "").strip() or None,
                        "trigger": pending_trigger,
                    }
                )
                pending_trigger = None
                continue
            if stripped and not stripped.startswith("//") and not stripped.startswith(("state ", "entry", "do ", "exit ")):
                # 其它语句（如 do/exit）不打断 trigger 注释的归属
                pending_trigger = None
        declaration["transitions"] = transitions


def extract_connections(text: str) -> Dict[str, Any]:
    """抽取 ``// Connection <id> flowKind=...`` + 下一行 ``connect a to b;`` 成对信息。

    这是 ``Connection`` 的逆解析入口：``connect`` 语句本身不带 IR id，因此
    结构化注释是还原 IR 的唯一依据。格式错误归入 ``malformed``，注释后没有
    对应 ``connect`` 语句归入 ``incomplete``；两者都由 ``lint_sysml`` 报错。
    """
    if not isinstance(text, str):
        return {"ok": False, "count": 0, "connections": [], "malformed": [], "incomplete": []}

    lines = text.split("\n")
    connections: List[Dict[str, Any]] = []
    malformed: List[Dict[str, Any]] = []
    incomplete: List[Dict[str, Any]] = []

    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped.startswith("// Connection"):
            index += 1
            continue
        column = len(raw) - len(raw.lstrip()) + 1
        match = CONNECTION_ANNOTATION_RE.match(stripped)
        if match is None:
            malformed.append(
                {
                    "line": index + 1,
                    "column": column,
                    "lineText": raw,
                    "message": "结构化 Connection 注释格式错误；应为 "
                    "`// Connection <id> flowKind=<flowKind>`"
                    "（可选 ` description: ...`）。",
                }
            )
            index += 1
            continue

        entry: Dict[str, Any] = {
            "id": match.group(1),
            "flowKind": match.group(2),
            "name": match.group(3),
            "description": match.group(4),
            "line": index + 1,
            "column": column,
            "lineText": raw,
            "source": None,
            "target": None,
            "connectLine": None,
        }
        cursor = index + 1
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        if cursor < len(lines):
            statement = CONNECT_STATEMENT_RE.match(lines[cursor].strip())
            if statement is not None:
                entry["source"] = statement.group(1)
                entry["target"] = statement.group(2)
                entry["connectLine"] = cursor + 1
        if entry["source"] is None:
            incomplete.append(entry)
        else:
            connections.append(entry)
        index = cursor + 1 if entry["source"] is not None else index + 1

    return {
        "ok": not malformed and not incomplete,
        "count": len(connections),
        "connections": connections,
        "malformed": malformed,
        "incomplete": incomplete,
    }


def _annotate_scopes(masked: str, declarations: List[Dict[str, Any]]) -> Dict[int, int]:
    """给每条声明算出它所在的最内层块，并标注该块的开括号属于哪条声明。

    :return: ``{开括号偏移: 闭括号偏移}``，供结构化注释的块范围计算复用。
    """
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

    return open_to_close


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
    额外比对：

    - ``PartUsage.typeRef``
    - ``Connection``：结构化注释里的 id / flowKind / name / 两端 name，与下方 ``connect``
      语句（``connect`` 语句本身没有 id，靠注释与 IR 对上）
    - ``Constraint``：体内 ``// expression:`` / ``// parameters:`` 两个结构化注释

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
    connection_scan = extract_connections(text)

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
        # Connection 没有具名声明，走结构化注释单独比对
        if isinstance(kind, str) and isinstance(name, str) and kind != "Connection":
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
        elif key[0] == "Constraint":
            props = element.get("properties") if isinstance(element.get("properties"), dict) else {}
            ir_expression = _normalize_inline(props.get("expression"))
            text_expression = _normalize_inline(declaration.get("expression"))
            if ir_expression != text_expression:
                mismatched.append(
                    {
                        "kind": key[0],
                        "name": key[1],
                        "id": element.get("id"),
                        "field": "expression",
                        "ir": props.get("expression"),
                        "text": declaration.get("expression"),
                        "line": declaration["line"],
                    }
                )
            ir_parameters = [
                name_by_id.get(parameter, parameter)
                for parameter in (props.get("parameters") or [])
                if isinstance(parameter, str)
            ]
            text_parameters = declaration.get("parameters")
            if text_parameters is None or ir_parameters != text_parameters:
                mismatched.append(
                    {
                        "kind": key[0],
                        "name": key[1],
                        "id": element.get("id"),
                        "field": "parameters",
                        "ir": ir_parameters,
                        "text": text_parameters,
                        "line": declaration["line"],
                    }
                )
        elif key[0] == "StateDefinition":
            props = element.get("properties") if isinstance(element.get("properties"), dict) else {}
            ir_initial = props.get("initial")
            text_initial = declaration.get("initial")
            if ir_initial != text_initial:
                mismatched.append(
                    {
                        "kind": key[0],
                        "name": key[1],
                        "id": element.get("id"),
                        "field": "initial",
                        "ir": ir_initial,
                        "text": text_initial,
                        "line": declaration["line"],
                    }
                )
            ir_transitions = [
                {
                    "from": item.get("from"),
                    "to": item.get("to"),
                    "trigger": _normalize_inline(item.get("trigger")),
                    "guard": _normalize_inline(item.get("guard")),
                }
                for item in (props.get("transitions") or [])
                if isinstance(item, dict)
            ]
            text_transitions = [
                {
                    "from": item.get("from"),
                    "to": item.get("to"),
                    "trigger": _normalize_inline(item.get("trigger")),
                    "guard": _normalize_inline(item.get("guard")),
                }
                for item in (declaration.get("transitions") or [])
            ]
            if ir_transitions != text_transitions:
                mismatched.append(
                    {
                        "kind": key[0],
                        "name": key[1],
                        "id": element.get("id"),
                        "field": "transitions",
                        "ir": ir_transitions,
                        "text": text_transitions,
                        "line": declaration["line"],
                    }
                )

    # ---- Connection：按结构化注释的 id 对齐 -------------------------------------------
    text_connections: Dict[str, Dict[str, Any]] = {}
    for entry in connection_scan["connections"]:
        text_connections.setdefault(entry["id"], entry)

    ir_connections = sorted(
        (e for e in elements if e.get("kind") == "Connection" and isinstance(e.get("id"), str)),
        key=lambda e: str(e.get("id")),
    )
    ir_connection_ids = {str(element.get("id")) for element in ir_connections}
    connection_missing = 0
    for element in ir_connections:
        connection_id = str(element.get("id"))
        entry = text_connections.get(connection_id)
        if entry is None:
            connection_missing += 1
            missing.append(
                {
                    "kind": "Connection",
                    "name": element.get("name"),
                    "id": element.get("id"),
                }
            )
            continue
        props = element.get("properties") if isinstance(element.get("properties"), dict) else {}
        for field, text_key in (("sourceRef", "source"), ("targetRef", "target")):
            reference = props.get(field)
            expected = name_by_id.get(reference, reference)
            if expected != entry.get(text_key):
                mismatched.append(
                    {
                        "kind": "Connection",
                        "name": element.get("name"),
                        "id": element.get("id"),
                        "field": field,
                        "ir": expected,
                        "irId": reference,
                        "text": entry.get(text_key),
                        "line": entry["connectLine"],
                    }
                )
        if props.get("flowKind") != entry.get("flowKind"):
            mismatched.append(
                {
                    "kind": "Connection",
                    "name": element.get("name"),
                    "id": element.get("id"),
                    "field": "flowKind",
                    "ir": props.get("flowKind"),
                    "text": entry.get("flowKind"),
                    "line": entry["line"],
                }
            )
        # name= 是 v2 新增；旧手写文本没有该字段时跳过比对，保持向后兼容
        if entry.get("name") is not None and element.get("name") != entry.get("name"):
            mismatched.append(
                {
                    "kind": "Connection",
                    "name": element.get("name"),
                    "id": element.get("id"),
                    "field": "name",
                    "ir": element.get("name"),
                    "text": entry.get("name"),
                    "line": entry["line"],
                }
            )
        description = props.get("description")
        if isinstance(description, str) and description:
            if _normalize_inline(description) != _normalize_inline(entry.get("description")):
                mismatched.append(
                    {
                        "kind": "Connection",
                        "name": element.get("name"),
                        "id": element.get("id"),
                        "field": "description",
                        "ir": description,
                        "text": entry.get("description"),
                        "line": entry["line"],
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
    for connection_id, entry in sorted(text_connections.items()):
        if connection_id not in ir_connection_ids:
            extra.append(
                {
                    "kind": "Connection",
                    "name": connection_id,
                    "line": entry["line"],
                    "column": entry["column"],
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
            "matched": len(ir_index) - len(missing) + len(ir_connections),
            "missing": len(missing),
            "extra": len(extra),
            "mismatched": len(mismatched),
            "lintErrors": len(lint["errors"]),
        },
        "declarationsByKind": extraction["byKind"],
        "connectionsByKind": connection_scan["count"],
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


def _normalize_inline(value: Any) -> Optional[str]:
    """把公式/描述文本折叠成单行，供 IR 与文本两侧同口径比较。"""
    if not isinstance(value, str):
        return None
    text = value.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return " ".join(text.split())


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
