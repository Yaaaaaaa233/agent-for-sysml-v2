"""``parse_sysml`` —— SysML v2 文本 → IR JSON 的**逆解析**（本工具链渲染子集）。

职责边界（先读这一段）
======================

本模块是 ``generate_sysml`` 的**逆过程**，只解析 ``mcp-server/schema/渲染约定.md``
所定义的那套渲染子集：

- 八种 kind 的声明：``part def`` / ``part`` / ``requirement def`` / ``action def`` /
  ``state def`` / ``attribute`` / ``constraint def`` / ``Connection`` 注释 + ``connect``；
- 后缀 ``[unit]``（Attribute）、``[n]``（PartUsage 多重度）；
- 状态机 ``entry; then X;`` 与 ``transition <name> first A [if (...)] then B;``，
  trigger 来自上一行 ``// trigger:``；
- ``Constraint`` 的 ``// expression:`` / ``// parameters:``；
- ``// description:``、``// id:``、``// Connection ...`` 与追溯关系注释块。

**它不是完整的 SysML v2 语言解析器。** 子集之外的构造（``item def``、``port``、
``satisfy``、裸 ``import``、多行块注释……）不会让本模块崩溃，也不会被静默丢弃：
每一条都会进入返回值里的 ``unsupported``（带行号与原文片段），并且 ``ok`` 为 ``False``。
这个界限是刻意的——把「认不出的东西」诚实交回给调用方，而不是猜一个 IR 出来。

返回结构::

    {"ok": bool, "model": dict | None, "warnings": [...],
     "unsupported": [{"line", "snippet", "reason"}],
     "errors": [...], "stats": {...}}

- ``model``：解析出的 IR（``schema = "sysml-ir/v1"``）。即使有 error / unsupported，
  只要顶层结构能建起来就返回**尽力而为**的 IR，方便调用方定位问题；完全无法解析时
  才是 ``None``。
- ``ok``：仅在「没有任何 error、也没有任何 unsupported」时为 ``True``。有 unsupported
  却返回 ``ok=True`` 会把「有损」说成「成功」，所以不这么做。
- 本模块**不代替** ``validate_model_json``：名字→id 的还原、owner 链、声明形态在这里
  处理，语义规则（需求必须有验收判据、typeRef 必须指向 PartDefinition 等）仍由校验器
  负责。固定流程是 ``parse_sysml`` → ``validate_model_json``。

名字 → id 的还原
================

文本里引用别的元素时写的是它的 ``name``（``PartUsage.typeRef``、``Constraint.parameters``、
``Connection`` 两端），而 IR 存的是 ``id``。本模块按「**同 owner 优先，其次全局唯一**」
解析；仍然唯一不了就报 ``E-PARSE-AMBIGUOUS``，解析不到报 ``E-PARSE-UNRESOLVED``，
**不瞎猜**。不同 owner 下同名元素会让文本本身失去唯一还原能力，这是渲染约定的已知限制
（见 ``渲染约定.md`` §5）。

元素自己的 ``id`` 从声明前的 ``// id: ...`` 注释还原（``generate_sysml`` 每个元素都会输出
这一行）；手写文本没有该注释时，会按 kind + name 合成一个确定性 id，并记一条 warning。

零第三方依赖，只用标准库；风格与 ``tools/sysml_lint.py`` 对齐。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# 复用生成器的「唯一事实」：kind 顺序、Requirement 保留字段、单位别名表。
# 这样渲染与逆解析不会各自漂移。
from .generator import (
    KIND_ORDER,
    REQUIREMENT_ORDERED_FIELDS,
    STANDARD_IMPORTS,
    UNIT_ALIASES,
)

SCHEMA_ID = "sysml-ir/v1"

#: 单位别名：IR 里的规范写法 → 生成文本里的写法（与 generator 共用 UNIT_ALIASES）
UNIT_ALIAS_TO_TEXT: Dict[str, str] = {source: text for source, text in UNIT_ALIASES}
UNIT_TEXT_TO_ALIAS: Dict[str, str] = {text: source for source, text in UNIT_ALIASES}

#: 文本里的 id 词法：允许连字符（IR id 只在注释里出现）
_ID = r"[A-Za-z_][A-Za-z0-9_-]*"
#: SysML 标识符（name）
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"

#: 合成 id 的 kind 前缀（手写文本没有 ``// id:`` 时使用）
ID_PREFIXES: Dict[str, str] = {
    "PartDefinition": "PART-DEF",
    "PartUsage": "PART-USE",
    "Requirement": "REQ",
    "ActionDefinition": "ACT",
    "StateDefinition": "STATE",
    "Attribute": "ATTR",
    "Constraint": "CONSTRAINT",
    "Connection": "CONN",
}

_PACKAGE_RE = re.compile(r"^package\s+(%s)\s*\{$" % _IDENT)
_PART_DEF_RE = re.compile(r"^(abstract\s+)?part\s+def\s+(%s)\s*([;{])$" % _IDENT)
_PART_USAGE_RE = re.compile(
    r"^part\s+(%s)\s*:\s*(%s)\s*(?:\[\s*([^\[\]]+?)\s*\])?\s*([;{])$"
    % (_IDENT, _IDENT)
)
_REQUIREMENT_RE = re.compile(r"^requirement\s+def\s+(%s)\s*([;{])$" % _IDENT)
_ACTION_RE = re.compile(r"^action\s+def\s+(%s)\s*([;{])$" % _IDENT)
_STATE_DEF_RE = re.compile(r"^state\s+def\s+(%s)\s*([;{])$" % _IDENT)
_CONSTRAINT_RE = re.compile(r"^constraint\s+def\s+(%s)\s*([;{])$" % _IDENT)
_STATE_RE = re.compile(r"^state\s+(%s)\s*;$" % _IDENT)
_ENTRY_RE = re.compile(r"^entry\s*;\s*then\s+(%s)\s*;$" % _IDENT)
_TRANSITION_RE = re.compile(
    r"^transition\s+(%s)\s+first\s+(%s)(?:\s+if\s*\((.*)\))?\s+then\s+(%s)\s*;$"
    % (_IDENT, _IDENT, _IDENT)
)
_ATTRIBUTE_RE = re.compile(
    r"^attribute\s+(%s)\s*:\s*(%s)\s*(.*)\s*([;{])$" % (_IDENT, _IDENT)
)
_PORT_RE = re.compile(r"^(in|out)\s+(%s)(?:\s*:\s*(%s))?\s*;$" % (_IDENT, _IDENT))
_IMPORT_RE = re.compile(r"^(private|public)\s+import\s+(.+?)\s*;$")
_DOC_RE = re.compile(r"\bdoc\s*/\*(.*?)\*/\s*$")

#: 关系注释：`//   SRC --type--> TARGET  (rationale)`（rationale 可省略）
_RELATION_ITEM_RE = re.compile(
    r"^(%s)\s+--(\w+)-->\s+(%s)(?:\s+\((.*)\))?$" % (_ID, _ID)
)

#: Connection 结构化注释（generator 输出 `// Connection <id> flowKind=... [name=...]
#: [description: ...]`；name 是 v2 逆解析新增，旧手写文本可省略）
_CONNECTION_NOTE_RE = re.compile(
    r"^Connection\s+(%s)\s+flowKind=(%s)(?:\s+name=(%s))?(?:\s+description:\s*(.*))?$"
    % (_ID, _IDENT, _IDENT)
)

_ID_COMMENT_RE = re.compile(r"^id:\s*(.*)$")
_DESCRIPTION_COMMENT_RE = re.compile(r"^description:\s*(.*)$")
_EXPRESSION_COMMENT_RE = re.compile(r"^expression:\s*(.*)$")
_PARAMETERS_COMMENT_RE = re.compile(r"^parameters:\s*(.*)$")
_TRIGGER_COMMENT_RE = re.compile(r"^trigger:\s*(.*)$")
_UNIT_COMMENT_RE = re.compile(r"^unit:\s*(.*)$")
_SECTION_COMMENT_RE = re.compile(r"^-{2,}\s*(.*?)\s*-{2,}$")

#: 文本语句的已知起始关键字；不在本模块子集里的，会进 unsupported（不是 error）
_KNOWN_KEYWORDS = frozenset(
    """
    package part abstract requirement action state attribute in out connect transition entry doc
    import private public constraint calc ref item port connection interface enum metadata
    satisfy verify allocate perform exhibit include accept if flow bind use actor objective
    subject message end comment view viewpoint concern analysis case
    """.split()
)

_MAX_SNIPPET = 160


# --------------------------------------------------------------------------------------
# 公共入口
# --------------------------------------------------------------------------------------


def parse_sysml(text: str) -> Dict[str, Any]:
    """把 SysML v2 文本逆解析成 IR JSON（仅限本工具链渲染子集）。

    :param text: SysML v2 文本（UTF-8 字符串）。生成器的输出、以及同子集的手写文本
        都可以解析；子集外构造会进 ``unsupported``，不会抛异常。
    :return: ``{"ok", "model", "warnings", "unsupported", "errors", "stats"}``，
        字段语义见模块文档。
    """
    if not isinstance(text, str):
        return {
            "ok": False,
            "model": None,
            "warnings": [],
            "unsupported": [],
            "errors": [
                {
                    "code": "E-PARSE-INPUT",
                    "line": 0,
                    "column": 0,
                    "message": "输入必须是 str，收到 %s。" % type(text).__name__,
                    "snippet": "",
                }
            ],
            "stats": {},
        }

    parser = _Parser(text)
    try:
        parser.run()
    except Exception as exc:  # noqa: BLE001 —— 不允许解析器把调用方拖崩
        parser.errors.append(
            {
                "code": "E-PARSE-INTERNAL",
                "line": 0,
                "column": 0,
                "message": "解析器内部异常（已捕获，返回尽力而为的结果）：%s" % exc,
                "snippet": "",
            }
        )

    model = parser.build_model()
    stats = parser.stats(model)
    ok = not parser.errors and not parser.unsupported
    return {
        "ok": ok,
        "model": model,
        "warnings": parser.warnings,
        "unsupported": parser.unsupported,
        "errors": parser.errors,
        "stats": stats,
    }


# --------------------------------------------------------------------------------------
# 解析器
# --------------------------------------------------------------------------------------


class _Parser:
    """行级状态机：块栈 + 待绑定注释 + 名字解析。

    选择行级解析（而不是写完整词法/语法分析器）是因为本模块只面对固定模板产出的
    文本：一行一条语句、花括号独占一行闭合。这样实现小、错误定位准，也符合
    ``sysml_lint`` 的既有风格。
    """

    def __init__(self, text: str) -> None:
        # 读取带 UTF-8 BOM 的文件时，BOM 会粘在第一行；先去掉，否则会被当成未知语句
        if text.startswith("\ufeff"):
            text = text[1:]
        self.text = text
        self.lines = text.split("\n")
        self.package = ""
        self.package_line = 0
        self.package_closed = False
        self.elements: List[Dict[str, Any]] = []
        self.by_id: Dict[str, Dict[str, Any]] = {}
        self.frames: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.unsupported: List[Dict[str, Any]] = []
        self.imports: List[str] = []
        self.synthesis_count = 0

        # 待绑定注释
        self.pending_id: Optional[Tuple[str, int]] = None
        self.pending_description: Optional[Tuple[str, int]] = None
        self.pending_trigger: Optional[Tuple[str, int]] = None
        self.pending_connection: Optional[Dict[str, Any]] = None

        # 延迟解析的引用：完整读完后才能做「同 owner 优先 / 全局唯一」判定
        self.ref_jobs: List[Dict[str, Any]] = []
        # 关系注释先收集，最后按注释里的源 id 归位（Connection 的关系不在元素块内）
        self.relation_entries: List[Dict[str, Any]] = []
        # 多行块注释状态
        self._in_block_comment = False

    # -- 主循环 -----------------------------------------------------------------------

    def run(self) -> None:
        for index, raw in enumerate(self.lines, 1):
            raw = raw.rstrip("\r")
            code, comment, in_block, was_in_block, started_block = _split_line(
                raw, self._in_block_comment
            )
            self._in_block_comment = in_block
            if was_in_block or started_block:
                # 多行块注释：本子集只支持单行 `doc /* ... */`；开头报一次 unsupported
                if started_block:
                    self.add_unsupported(
                        index,
                        raw,
                        "多行块注释不在渲染子集内（doc 只支持单行 `doc /* ... */`），"
                        "其内容未被解析。",
                    )
                if self._is_suppressed():
                    self._track_suppressed(code)
                continue

            stripped = code.strip()

            # 不支持块内部：只跟踪花括号，避免内部语句被误解析
            if self._is_suppressed():
                self._track_suppressed(code)
                continue

            if stripped == "":
                if comment is not None:
                    self.handle_comment(comment, index, raw)
                continue

            if self.package_closed:
                self.add_unsupported(
                    index,
                    raw,
                    "`package` 块闭合之后的内容不在本子集内（一个文件只有一个顶层 package）。",
                )
                self._push_unsupported_block(stripped, index)
                continue

            # 纯注释行 / 代码行都可能带行尾注释：先处理语句，再处理**非结构化**行尾注释
            if stripped in ("}", "};"):
                self.handle_close(index, raw, comment)
                continue

            if stripped.startswith("doc") and "/*" in raw:
                self.handle_doc(raw, index, comment)
                continue

            handled = self.handle_statement(stripped, index, raw, comment)
            if not handled:
                self.add_unsupported(
                    index,
                    raw,
                    "不在本工具链渲染子集内的语句（parse_sysml 不是完整 SysML v2 解析器）。",
                )
                self._push_unsupported_block(stripped, index)

        self.finish()

    # -- 关闭块 -----------------------------------------------------------------------

    def handle_close(self, line: int, raw: str, comment: Optional[str]) -> None:
        if not self.frames:
            self.add_error("E-PARSE-UNBALANCED", line, raw, "多余的 `}`：没有打开的块。")
            return
        if self._is_suppressed():
            self._track_suppressed("}")
            return
        frame = self.frames.pop()
        if frame["kind"] == "Package":
            self.package_closed = True
            return
        element = frame.get("element")
        if element is not None and element.get("kind") == "StateDefinition":
            if self.pending_trigger is not None:
                self.add_warning(
                    "W-PARSE-TRIGGER-UNUSED",
                    self.pending_trigger[1],
                    "`// trigger:` 没有对应的 transition，已忽略。",
                )
                self.pending_trigger = None
        self._warn_dangling_meta(frame)

    def _warn_dangling_meta(self, frame: Dict[str, Any]) -> None:
        """块结束时仍未绑定的 id/description 注释：如实提示，不静默塞给下一个元素。"""
        for attribute, code, label in (
            ("pending_id", "W-PARSE-ID-UNUSED", "`// id:`"),
            ("pending_description", "W-PARSE-DESC-UNUSED", "`// description:`"),
        ):
            pending = getattr(self, attribute)
            if pending is None:
                continue
            value, pending_line = pending
            if pending_line > frame.get("line", 0):
                self.add_warning(
                    code,
                    pending_line,
                    "%s 注释（%s）没有对应的声明，已忽略。" % (label, value),
                )
                setattr(self, attribute, None)

    # -- 语句 -------------------------------------------------------------------------

    def handle_statement(
        self, stripped: str, line: int, raw: str, comment: Optional[str]
    ) -> bool:
        """返回 True 表示这条语句属于子集（无论是否合法）；False 表示子集外。"""

        # 1) package
        match = _PACKAGE_RE.match(stripped)
        if match:
            self._handle_package(match.group(1), line, raw)
            return True

        # 2) 八种 kind 的声明
        match = _PART_DEF_RE.match(stripped)
        if match:
            props: Dict[str, Any] = {}
            if match.group(1):
                props["isAbstract"] = True
            element = self.create_element("PartDefinition", match.group(2), line, raw, props)
            self._open_or_close(element, match.group(3), line)
            return True

        match = _PART_USAGE_RE.match(stripped)
        if match:
            props = {"typeRef": match.group(2)}
            if match.group(3) is not None:
                quantity = _parse_number(match.group(3))
                if quantity is None:
                    self.add_error(
                        "E-PARSE-QUANTITY",
                        line,
                        raw,
                        "PartUsage 多重度必须是单一数字（本约定不支持 `[1..4]` / `[0..*]`）。",
                    )
                else:
                    props["quantity"] = quantity
            element = self.create_element("PartUsage", match.group(1), line, raw, props)
            self.ref_jobs.append(
                {
                    "kind": "typeRef",
                    "element": element,
                    "name": match.group(2),
                    "owner": element["owner"],
                    "line": line,
                }
            )
            self._open_or_close(element, match.group(4), line)
            return True

        match = _REQUIREMENT_RE.match(stripped)
        if match:
            element = self.create_element("Requirement", match.group(1), line, raw, {})
            self._open_or_close(element, match.group(2), line)
            return True

        match = _ACTION_RE.match(stripped)
        if match:
            element = self.create_element(
                "ActionDefinition",
                match.group(1),
                line,
                raw,
                {"inputs": [], "outputs": []},
            )
            self._open_or_close(element, match.group(2), line)
            return True

        match = _STATE_DEF_RE.match(stripped)
        if match:
            element = self.create_element(
                "StateDefinition", match.group(1), line, raw, {"states": []}
            )
            self._open_or_close(element, match.group(2), line)
            return True

        match = _CONSTRAINT_RE.match(stripped)
        if match:
            element = self.create_element("Constraint", match.group(1), line, raw, {})
            self._open_or_close(element, match.group(2), line)
            return True

        # 3) 状态机语句
        current = self.current_element()
        match = _STATE_RE.match(stripped)
        if match:
            if current is None or current.get("kind") != "StateDefinition":
                return False
            current["properties"].setdefault("states", []).append(match.group(1))
            return True

        match = _ENTRY_RE.match(stripped)
        if match:
            if current is None or current.get("kind") != "StateDefinition":
                return False
            if "initial" in current["properties"]:
                self.add_warning(
                    "W-PARSE-INITIAL-DUPLICATE",
                    line,
                    "状态机出现多条 `entry; then ...;`，以最后一条为准。",
                )
            current["properties"]["initial"] = match.group(1)
            return True

        match = _TRANSITION_RE.match(stripped)
        if match:
            if current is None or current.get("kind") != "StateDefinition":
                return False
            transition: Dict[str, Any] = {
                "from": match.group(2),
                "to": match.group(4),
            }
            guard = (match.group(3) or "").strip()
            if guard:
                transition["guard"] = " ".join(guard.split())
            if self.pending_trigger is not None:
                trigger, _trigger_line = self.pending_trigger
                if trigger.strip():
                    transition["trigger"] = " ".join(trigger.split())
                self.pending_trigger = None
            current["properties"].setdefault("transitions", []).append(transition)
            return True

        # 4) Attribute / Requirement 字段
        match = _ATTRIBUTE_RE.match(stripped)
        if match:
            element = self._handle_attribute(
                match.group(1), match.group(2), match.group(3), line, raw, comment
            )
            if match.group(4) == "{":
                if element is None:
                    self.add_error(
                        "E-PARSE-ATTRIBUTE",
                        line,
                        raw,
                        "requirement def 体内的阈值/字段不能带 `{ ... }` 体。",
                    )
                else:
                    self._open_or_close(element, "{", line)
            return True

        # 5) Action 端口
        match = _PORT_RE.match(stripped)
        if match:
            if current is None or current.get("kind") != "ActionDefinition":
                return False
            port: Dict[str, Any] = {"name": match.group(2)}
            if match.group(3):
                port["typeRef"] = match.group(3)
            unit = _unit_from_comment(comment)
            if unit:
                port["unit"] = unit
            key = "inputs" if match.group(1) == "in" else "outputs"
            current["properties"].setdefault(key, []).append(port)
            return True

        # 6) Connection
        match = _IMPORT_RE.match(stripped)
        if match:
            self._handle_import(match.group(1), match.group(2), line, raw)
            return True

        if stripped.startswith("connect"):
            return self._handle_connect(stripped, line, raw)

        # 7) 认得出关键字但不在子集内：交给调用方记 unsupported
        head = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", stripped)
        if head and head.group(1) in _KNOWN_KEYWORDS:
            return False
        return False

    # -- 各类语句的具体处理 -------------------------------------------------------------

    def _handle_package(self, name: str, line: int, raw: str) -> None:
        if self.package:
            self.add_unsupported(line, raw, "本子集只支持一个顶层 `package` 块。")
            self._push_unsupported_block("package {", line)
            return
        if self.frames:
            self.add_unsupported(line, raw, "`package` 只能出现在顶层。")
            self._push_unsupported_block("package {", line)
            return
        self.package = name
        self.package_line = line
        self.frames.append(
            {"kind": "Package", "element": None, "line": line, "depth": 1}
        )

    def _handle_import(self, qualifier: str, target: str, line: int, raw: str) -> None:
        statement = "%s import %s;" % (qualifier, target.strip())
        normalized = "%s import %s;" % (qualifier, " ".join(target.split()))
        self.imports.append(normalized)
        # 生成器只输出 private；手写文本里的 public import 语义等价，也认。
        standard_targets = {
            item.split(" import ", 1)[1].rstrip(";") for item in STANDARD_IMPORTS
        }
        if " ".join(target.split()) in standard_targets:
            return
        self.add_unsupported(
            line,
            raw,
            "非生成器固定头的 import（`%s`）不落进 IR；重新 generate 时只输出标准库 "
            "import 头，因此该行不会被保留。" % statement,
        )

    def _handle_attribute(
        self,
        name: str,
        value_type: str,
        rest: str,
        line: int,
        raw: str,
        comment: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        current = self.current_element()
        default_text, unit_text, parse_error = _split_default_and_unit(rest)
        if parse_error:
            self.add_error("E-PARSE-ATTRIBUTE", line, raw, parse_error)
            return None

        # Requirement 的体内 attribute 有两种：保留字符串字段 / 数值阈值
        if current is not None and current.get("kind") == "Requirement":
            if value_type == "String":
                if name not in REQUIREMENT_ORDERED_FIELDS:
                    self.add_unsupported(
                        line,
                        raw,
                        "requirement def 体内的 String attribute 只支持 %s；"
                        "`text` / `acceptanceCriteria` / `description` 由 doc 或注释承载。"
                        % "、".join(REQUIREMENT_ORDERED_FIELDS),
                    )
                    return None
                value, error = _parse_literal(default_text, "String")
                if error:
                    self.add_error("E-PARSE-LITERAL", line, raw, error)
                    return None
                current["properties"][name] = value
                return None
            value, error = _parse_literal(default_text, value_type)
            if error:
                self.add_error("E-PARSE-LITERAL", line, raw, error)
                return None
            if unit_text:
                unit = _parse_unit(unit_text)
                if isinstance(value, (int, float, bool)):
                    current["properties"][name] = {"value": value, "unit": unit}
                else:
                    self.add_error(
                        "E-PARSE-REQ-FIELD",
                        line,
                        raw,
                        "Requirement 阈值只能是数字 / 布尔 / {value, unit}，`%s` 不合法。"
                        % name,
                    )
                return None
            current["properties"][name] = value
            return None

        # 独立 Attribute 元素
        props: Dict[str, Any] = {"valueType": value_type}
        if default_text is not None:
            value, error = _parse_literal(default_text, value_type)
            if error:
                self.add_error("E-PARSE-LITERAL", line, raw, error)
                return None
            props["defaultValue"] = value
        if unit_text:
            props["unit"] = _parse_unit(unit_text)
        return self.create_element("Attribute", name, line, raw, props)

    def _handle_connect(self, stripped: str, line: int, raw: str) -> bool:
        match = re.match(
            r"^connect\s+(%s)\s+to\s+(%s)\s*;$" % (_IDENT, _IDENT), stripped
        )
        if match is None:
            self.add_error(
                "E-PARSE-CONNECT",
                line,
                raw,
                "`connect` 语句必须是 `connect <src> to <tgt>;`。",
            )
            return True

        note = self.pending_connection
        if note is None:
            self.add_unsupported(
                line,
                raw,
                "缺少上一行 `// Connection <id> flowKind=...` 结构化注释，"
                "无法还原 Connection 的 id / flowKind。",
            )
            return True
        self.pending_connection = None

        if note.get("error"):
            return True

        props = {
            "sourceRef": match.group(1),
            "targetRef": match.group(2),
            "flowKind": note["flowKind"],
        }
        if note.get("description"):
            props["description"] = note["description"]

        previous_id = self.pending_id
        self.pending_id = (note["id"], note["line"])
        name = note.get("name")
        if name is None:
            name = self._synth_connection_name(match.group(1), match.group(2))
            self.add_warning(
                "W-PARSE-CONN-NAME",
                note["line"],
                "`// Connection` 注释缺少 `name=`，已合成 Connection 名称 `%s`。" % name,
            )
        element = self.create_element("Connection", name, line, raw, props)
        self.pending_id = previous_id
        self.ref_jobs.append(
            {
                "kind": "sourceRef",
                "element": element,
                "name": match.group(1),
                "owner": element["owner"],
                "line": line,
            }
        )
        self.ref_jobs.append(
            {
                "kind": "targetRef",
                "element": element,
                "name": match.group(2),
                "owner": element["owner"],
                "line": line,
            }
        )
        return True

    def _synth_connection_name(self, source: str, target: str) -> str:
        base = "%sTo%s" % (source, target[:1].upper() + target[1:])
        return _dedupe_name(base, {e.get("name") for e in self.elements})

    # -- 注释 -------------------------------------------------------------------------

    def handle_comment(self, comment: str, line: int, raw: str) -> None:
        stripped = comment.strip()
        if not stripped:
            return
        if stripped.startswith("Generated by sysml-modeling-agent"):
            return
        if stripped.startswith("Source of truth is the IR JSON"):
            return

        if _SECTION_COMMENT_RE.match(stripped):
            # 分节标题只是可读性；kind 名字写错时提示一下，不影响语义
            name = _SECTION_COMMENT_RE.match(stripped).group(1).strip()
            if name and name not in KIND_ORDER:
                self.add_warning(
                    "W-PARSE-SECTION",
                    line,
                    "未知的分节标题 `%s`（已忽略）。" % name,
                )
            return

        match = _ID_COMMENT_RE.match(stripped)
        if match:
            if self.pending_id is not None:
                self.add_warning(
                    "W-PARSE-ID-OVERWRITTEN",
                    line,
                    "上一条 `// id:` 尚未绑定就被新的覆盖（旧值 `%s`）。"
                    % self.pending_id[0],
                )
            self.pending_id = (match.group(1).strip(), line)
            return

        match = _DESCRIPTION_COMMENT_RE.match(stripped)
        if match:
            self.pending_description = (match.group(1).strip(), line)
            return

        if stripped.startswith("追溯关系 (relations):"):
            # 标题本身不承载信息；关系项按行解析、按源 id 归位
            return

        match = _RELATION_ITEM_RE.match(stripped)
        if match:
            current = self.current_element()
            self.relation_entries.append(
                {
                    "src": match.group(1),
                    "type": match.group(2),
                    "target": match.group(3),
                    "rationale": match.group(4),
                    "line": line,
                    "context": current.get("id") if current else None,
                }
            )
            return

        match = _EXPRESSION_COMMENT_RE.match(stripped)
        if match:
            current = self.current_element()
            if current is None or current.get("kind") != "Constraint":
                self.add_unsupported(
                    line,
                    raw,
                    "`// expression:` 只应出现在 `constraint def` 体内。",
                )
                return
            current["properties"]["expression"] = " ".join(match.group(1).split())
            return

        match = _PARAMETERS_COMMENT_RE.match(stripped)
        if match:
            current = self.current_element()
            if current is None or current.get("kind") != "Constraint":
                self.add_unsupported(
                    line,
                    raw,
                    "`// parameters:` 只应出现在 `constraint def` 体内。",
                )
                return
            names = [item.strip() for item in match.group(1).split(",") if item.strip()]
            current["properties"]["parameters"] = names
            self.ref_jobs.append(
                {
                    "kind": "parameters",
                    "element": current,
                    "names": names,
                    "owner": current["owner"],
                    "line": line,
                }
            )
            return

        match = _TRIGGER_COMMENT_RE.match(stripped)
        if match:
            current = self.current_element()
            if current is None or current.get("kind") != "StateDefinition":
                self.add_unsupported(
                    line,
                    raw,
                    "`// trigger:` 只应出现在 `state def` 体内、transition 上一行。",
                )
                return
            self.pending_trigger = (match.group(1), line)
            return

        match = _CONNECTION_NOTE_RE.match(stripped)
        if match:
            if self.pending_connection is not None:
                self.add_error(
                    "E-PARSE-CONN-NO-CONNECT",
                    self.pending_connection["line"],
                    "上一条 `// Connection` 注释",
                    "`// Connection ...` 注释下方必须紧跟一条 `connect <src> to <tgt>;` 语句。",
                )
            self.pending_connection = {
                "id": match.group(1),
                "flowKind": match.group(2),
                "name": match.group(3),
                "description": match.group(4),
                "line": line,
            }
            return

        if stripped.startswith("Connection"):
            self.pending_connection = {"error": True, "line": line}
            self.add_error(
                "E-PARSE-CONN-ANNOTATION",
                line,
                raw,
                "结构化 Connection 注释格式错误；应为 `// Connection <id> "
                "flowKind=<flowKind> [name=<name>] [description: ...]`。",
            )
            return

        # 其余都是普通注释（可以是任意说明），忽略
        return

    def handle_doc(self, raw: str, line: int, comment: Optional[str]) -> None:
        current = self.current_element()
        match = _DOC_RE.search(raw)
        if match is None:
            self.add_unsupported(
                line,
                raw,
                "`doc` 只支持单行 `doc /* ... */`（本渲染子集的形态）。",
            )
            return
        if current is None or current.get("kind") != "Requirement":
            self.add_unsupported(line, raw, "`doc` 只应出现在 `requirement def` 体内。")
            return
        content = match.group(1).strip()
        prefix = "验收判据:"
        if content.startswith(prefix):
            current["properties"]["acceptanceCriteria"] = content[len(prefix) :].strip()
            return
        current["properties"]["text"] = content
        return

    # -- 元素与块 ---------------------------------------------------------------------

    def create_element(
        self,
        kind: str,
        name: str,
        line: int,
        raw: str,
        properties: Dict[str, Any],
    ) -> Dict[str, Any]:
        element_id, description = self._consume_meta(kind, name, line, raw)
        owner = self.current_owner()
        element: Dict[str, Any] = {
            "id": element_id,
            "kind": kind,
            "name": name,
            "owner": owner,
            "properties": properties,
        }
        if description is not None:
            properties["description"] = description
        if element_id in self.by_id:
            self.add_error(
                "E-PARSE-DUPLICATE-ID",
                line,
                raw,
                "元素 id `%s` 重复（同 id 的 IR 不合法）。" % element_id,
            )
        else:
            self.by_id[element_id] = element
        for sibling in self.elements:
            if sibling.get("owner") == owner and sibling.get("name") == name:
                self.add_error(
                    "E-PARSE-DUPLICATE-NAME",
                    line,
                    raw,
                    "同一 owner `%s` 下出现重名元素 `%s`（IR 不允许）。" % (owner, name),
                )
                break
        self.elements.append(element)
        return element

    def _consume_meta(
        self, kind: str, name: str, line: int, raw: str
    ) -> Tuple[str, Optional[str]]:
        description: Optional[str] = None
        if self.pending_description is not None:
            description, _desc_line = self.pending_description
            self.pending_description = None

        if self.pending_id is not None:
            candidate, id_line = self.pending_id
            self.pending_id = None
            if not _is_id(candidate):
                self.add_error(
                    "E-PARSE-BAD-ID",
                    id_line,
                    raw,
                    "`// id:` 的值 `%s` 不是合法 IR id（需匹配 ^[A-Za-z_][A-Za-z0-9_-]*$）。"
                    % candidate,
                )
            elif candidate in self.by_id:
                self.add_error(
                    "E-PARSE-DUPLICATE-ID",
                    id_line,
                    raw,
                    "`// id:` 的值 `%s` 与已有元素重复。" % candidate,
                )
            else:
                return candidate, description

        return self._synth_id(kind, name), description

    def _synth_id(self, kind: str, name: str) -> str:
        prefix = ID_PREFIXES.get(kind, "ELEM")
        base = "%s-%s" % (prefix, name)
        candidate = base
        suffix = 2
        while candidate in self.by_id:
            candidate = "%s-%d" % (base, suffix)
            suffix += 1
        self.synthesis_count += 1
        return candidate

    def _open_or_close(self, element: Dict[str, Any], terminator: str, line: int) -> None:
        if terminator == "{":
            self.frames.append(
                {
                    "kind": element["kind"],
                    "element": element,
                    "line": line,
                    "depth": 1,
                }
            )

    def current_element(self) -> Optional[Dict[str, Any]]:
        for frame in reversed(self.frames):
            if frame.get("element") is not None:
                return frame["element"]
        return None

    def current_owner(self) -> str:
        element = self.current_element()
        return element["id"] if element is not None else self.package

    # -- 不支持块的兜底 ---------------------------------------------------------------

    def _is_suppressed(self) -> bool:
        return bool(self.frames) and self.frames[-1].get("kind") == "__unsupported__"

    def _push_unsupported_block(self, code: str, line: int = 0) -> None:
        opens = code.count("{")
        closes = code.count("}")
        depth = opens - closes
        if depth > 0:
            self.frames.append({"kind": "__unsupported__", "line": line, "depth": depth})

    def _track_suppressed(self, code: str) -> None:
        if not self.frames:
            return
        frame = self.frames[-1]
        frame["depth"] += code.count("{") - code.count("}")
        if frame["depth"] <= 0:
            self.frames.pop()

    # -- 完成后处理 -------------------------------------------------------------------

    def finish(self) -> None:
        if not self.package:
            self.add_error(
                "E-PARSE-NO-PACKAGE",
                0,
                "",
                "文本里没有 `package <Name> { ... }` 顶层包裹。",
            )
        for frame in self.frames:
            if frame.get("kind") == "__unsupported__":
                self.add_error(
                    "E-PARSE-UNCLOSED",
                    frame.get("line", 0),
                    "",
                    "子集外的块没有闭合（解析已跳过其内容）。",
                )
                continue
            element = frame.get("element")
            label = element.get("name") if element else self.package
            self.add_error(
                "E-PARSE-UNCLOSED",
                frame.get("line", 0),
                "",
                "块 `%s` 没有闭合的 `}`。" % label,
            )
        if self.pending_connection is not None:
            self.add_error(
                "E-PARSE-CONN-NO-CONNECT",
                self.pending_connection.get("line", 0),
                "",
                "`// Connection ...` 注释下方必须紧跟一条 `connect <src> to <tgt>;` 语句。",
            )
            self.pending_connection = None
        for attribute, code, label in (
            ("pending_id", "W-PARSE-ID-UNUSED", "`// id:`"),
            ("pending_description", "W-PARSE-DESC-UNUSED", "`// description:`"),
            ("pending_trigger", "W-PARSE-TRIGGER-UNUSED", "`// trigger:`"),
        ):
            pending = getattr(self, attribute)
            if pending is not None:
                self.add_warning(
                    code,
                    pending[1],
                    "%s 注释在文件末尾仍没有绑定对象，已忽略。" % label,
                )
                setattr(self, attribute, None)

        self._resolve_references()
        self._attach_relations()

        if self.synthesis_count:
            self.add_warning(
                "W-PARSE-SYNTH-ID",
                0,
                "文本中有 %d 个元素缺少 `// id:` 注释，已按 kind + name 合成确定性 id；"
                "重新 generate 后这些 id 会写进文本。" % self.synthesis_count,
            )

    def _resolve_references(self) -> None:
        for job in self.ref_jobs:
            if job["kind"] == "parameters":
                resolved: List[str] = []
                names: List[str] = job["names"]
                for name in names:
                    target, error = self.resolve(name, job["owner"], ("Attribute",))
                    if error:
                        self.add_error(
                            error[0], job["line"], "", error[1]
                        )
                        resolved.append(name)
                    else:
                        resolved.append(target["id"])
                job["element"]["properties"]["parameters"] = resolved
                continue

            target, error = self.resolve(
                job["name"],
                job["owner"],
                ("PartDefinition",) if job["kind"] == "typeRef" else ("PartUsage",),
            )
            if error:
                self.add_error(error[0], job["line"], "", error[1])
                continue
            job["element"]["properties"][job["kind"]] = target["id"]

    def resolve(
        self, name: str, owner: str, kinds: Tuple[str, ...]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[str, str]]]:
        candidates = [
            element
            for element in self.elements
            if element.get("name") == name and element.get("kind") in kinds
        ]
        same_owner = [element for element in candidates if element.get("owner") == owner]
        pool = same_owner or candidates
        if len(pool) == 1:
            return pool[0], None
        if not pool:
            return None, (
                "E-PARSE-UNRESOLVED",
                "名字 `%s` 在 %s 中找不到（owner `%s`）；文本引用只能写 name，"
                "无法还原成 IR id。" % (name, "、".join(kinds), owner),
            )
        identifiers = "、".join(sorted(str(item.get("id")) for item in pool))
        return None, (
            "E-PARSE-AMBIGUOUS",
            "名字 `%s` 无法唯一还原（候选：%s）；同 owner 优先后仍歧义，"
            "不猜测具体指向。" % (name, identifiers),
        )

    def _attach_relations(self) -> None:
        for entry in self.relation_entries:
            target = self.by_id.get(entry["src"])
            if target is None:
                context = self.by_id.get(entry["context"]) if entry.get("context") else None
                if context is None:
                    self.add_error(
                        "E-PARSE-RELATION-SOURCE",
                        entry["line"],
                        "",
                        "追溯注释的源 id `%s` 不是已知元素，也没有可归属的上下文元素。"
                        % entry["src"],
                    )
                    continue
                self.add_warning(
                    "W-PARSE-RELATION-SOURCE",
                    entry["line"],
                    "追溯注释的源 id `%s` 不是已知元素，已按所在元素 `%s` 归属。"
                    % (entry["src"], context["id"]),
                )
                target = context
            relation: Dict[str, Any] = {
                "type": entry["type"],
                "target": entry["target"],
            }
            if entry["rationale"] is not None and entry["rationale"].strip():
                relation["rationale"] = entry["rationale"].strip()
            target.setdefault("relations", []).append(relation)

    # -- 结果 -------------------------------------------------------------------------

    def build_model(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA_ID,
            "package": self.package,
            "elements": self.elements,
        }

    def stats(self, model: Dict[str, Any]) -> Dict[str, Any]:
        elements = model["elements"]
        by_kind = {kind: 0 for kind in KIND_ORDER}
        for element in elements:
            kind = element.get("kind")
            if kind in by_kind:
                by_kind[kind] += 1
        return {
            "lines": self.text.count("\n") + (0 if self.text.endswith("\n") else 1),
            "chars": len(self.text),
            "package": self.package,
            "elements": len(elements),
            "byKind": by_kind,
            "relations": sum(len(element.get("relations") or []) for element in elements),
            "imports": len(self.imports),
            "synthesizedIds": self.synthesis_count,
            "unsupported": len(self.unsupported),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
        }

    # -- 报告 -------------------------------------------------------------------------

    def add_error(self, code: str, line: int, raw: str, message: str) -> None:
        self.errors.append(
            {
                "code": code,
                "line": line,
                "column": _column_of(raw),
                "message": message,
                "snippet": _snippet(raw),
            }
        )

    def add_warning(self, code: str, line: int, message: str) -> None:
        self.warnings.append({"code": code, "line": line, "message": message})

    def add_unsupported(self, line: int, raw: str, reason: str) -> None:
        self.unsupported.append(
            {"line": line, "snippet": _snippet(raw), "reason": reason}
        )


# --------------------------------------------------------------------------------------
# 词法小工具
# --------------------------------------------------------------------------------------


def _split_line(
    raw: str, in_block: bool
) -> Tuple[str, Optional[str], bool, bool, bool]:
    """把一行拆成 ``(代码, 行注释, 行末是否仍在块注释, 行首是否在块注释, 本行是否开启块注释)``。

    - ``//`` 与 ``/* */`` 的内容不进入代码，因此花括号/分号计数不会被注释干扰；
    - 字符串字面量原样保留（``attribute x : String = "a;b";`` 需要完整取到引号内容）；
    - 块注释可跨行，由调用方维护状态。
    """
    out: List[str] = []
    comment: Optional[str] = None
    was_in_block = in_block
    started_block = False
    index = 0
    length = len(raw)
    while index < length:
        ch = raw[index]
        if in_block:
            if raw.startswith("*/", index):
                in_block = False
                index += 2
                continue
            index += 1
            continue
        if raw.startswith("//", index):
            comment = raw[index + 2 :]
            break
        if raw.startswith("/*", index):
            end = raw.find("*/", index + 2)
            if end == -1:
                in_block = True
                started_block = True
                index += 2
            else:
                index = end + 2
            continue
        if ch == '"':
            out.append(ch)
            index += 1
            while index < length:
                out.append(raw[index])
                if raw[index] == "\\" and index + 1 < length:
                    out.append(raw[index + 1])
                    index += 2
                    continue
                if raw[index] == '"':
                    index += 1
                    break
                index += 1
            continue
        out.append(ch)
        index += 1
    return "".join(out), comment, in_block, was_in_block, started_block


def _split_default_and_unit(rest: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """拆 ``attribute`` 行尾的 ``= <value> [unit]`` / ``[unit]``。

    返回 ``(默认值文本, 单位文本, 错误说明)``；没有默认值时第一项为 ``None``。
    """
    text = rest.strip()
    if not text:
        return None, None, None
    if not text.startswith("="):
        # generator 允许「有单位、无默认值」：`attribute x : Real [V];`
        if text.startswith("[") and text.endswith("]"):
            unit = text[1:-1].strip()
            if not unit:
                return None, None, "单位 `[...]` 不能为空。"
            return None, unit, None
        return None, None, "attribute 行只能形如 `attribute name : Type [= value] [unit];`。"
    body = text[1:].strip()
    unit: Optional[str] = None
    if body.endswith("]") and "[" in body:
        bracket = body.rfind("[")
        unit = body[bracket + 1 : -1].strip()
        body = body[:bracket].strip()
        if not unit:
            return None, None, "单位 `[...]` 不能为空。"
    if not body:
        return None, None, "`=` 之后缺少默认值。"
    return body, unit, None


def _parse_literal(text: Optional[str], value_type: str) -> Tuple[Any, Optional[str]]:
    """按 ``valueType`` 解析字面量；失败返回 ``(None, 错误说明)``。"""
    if text is None:
        return None, "缺少默认值。"
    raw = text.strip()
    if value_type == "String":
        try:
            value = json.loads(raw)
        except Exception:  # noqa: BLE001
            return None, "String 默认值必须是合法 JSON 字符串字面量（带双引号）。"
        if not isinstance(value, str):
            return None, "String 默认值必须是字符串。"
        return value, None
    if value_type == "Boolean":
        if raw == "true":
            return True, None
        if raw == "false":
            return False, None
        return None, "Boolean 默认值只能是 `true` / `false`。"
    if value_type == "Integer":
        if re.match(r"^[+-]?\d+$", raw):
            return int(raw), None
        return None, "Integer 默认值必须是整数字面量。"
    if value_type == "Real":
        if re.match(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$", raw):
            return float(raw), None
        return None, "Real 默认值必须是数字字面量。"
    # 未知 valueType：先按数字/布尔/字符串兜底，真正的类型问题交给 validator
    number = _parse_number(raw)
    if number is not None:
        return number, None
    if raw in ("true", "false"):
        return raw == "true", None
    try:
        return json.loads(raw), None
    except Exception:  # noqa: BLE001
        return raw, None


def _parse_number(text: str) -> Optional[Any]:
    """``1`` → int，``1.0`` / ``1e3`` → float；不是数字返回 ``None``。"""
    raw = text.strip()
    if re.match(r"^[+-]?\d+$", raw):
        return int(raw)
    if re.match(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$", raw):
        return float(raw)
    return None


def _parse_unit(text: str) -> str:
    """文本单位 → IR 单位：执行 ``UNIT_ALIASES`` 的逆映射（``W*h`` → ``Wh``）。"""
    cleaned = " ".join(text.split())
    return UNIT_TEXT_TO_ALIAS.get(cleaned, cleaned)


def _unit_from_comment(comment: Optional[str]) -> Optional[str]:
    if not comment:
        return None
    match = _UNIT_COMMENT_RE.match(comment.strip())
    if match is None:
        return None
    value = match.group(1).strip()
    return value or None


def _is_id(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", value))


def _dedupe_name(base: str, used: set) -> str:
    if base not in used:
        return base
    index = 2
    while "%s%d" % (base, index) in used:
        index += 1
    return "%s%d" % (base, index)


def _column_of(raw: str) -> int:
    if not raw:
        return 1
    return len(raw) - len(raw.lstrip()) + 1


def _snippet(raw: str) -> str:
    return raw.strip()[:_MAX_SNIPPET]


# --------------------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) < 2:
        print("用法：python -m tools.parser <model.sysml>")
        raise SystemExit(2)
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        content = handle.read()
    outcome = parse_sysml(content)
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    raise SystemExit(0 if outcome.get("ok") else 1)
