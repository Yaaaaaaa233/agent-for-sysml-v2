"""``validate_model_json`` —— 以 Schema + 语义规则校验 IR JSON。

技术方案 4.4 设计原则的可执行版本：

1. 必填字段明确（id/kind/name/owner/properties）
2. 枚举受控（kind、relations[].type、valueType、verifyMethod、priority）
3. 引用必须存在（relations[].target、PartUsage.typeRef）
4. 命名唯一（id 全局唯一；同 owner 下 name 唯一）
5. 数值字段必须是数字（阈值不许写成字符串）

实现取向（见 README「可选依赖」）：
核心规则 **全部用纯标准库实现**，因此无第三方依赖也能完整工作；
若环境装有 ``jsonschema``，会额外跑一遍 ``schema/sysml-ir-v1.json`` 作为第二层
交叉检查，把 Python 规则引擎没有覆盖到的「形状」问题（未知字段名、类型不符等）
以 ``E-SCHEMA`` 补充进来（已由 Python 层报过的位置会被去重跳过）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

SCHEMA_FILENAME = "sysml-ir-v1.json"
SCHEMA_ID = "sysml-ir/v1"

KINDS: Tuple[str, ...] = (
    "PartDefinition",
    "PartUsage",
    "Requirement",
    "ActionDefinition",
    "StateDefinition",
    "Attribute",
)

RELATION_TYPES: Tuple[str, ...] = (
    "refines",
    "satisfiedBy",
    "decomposes",
    "verifies",
    "connects",
)

#: Attribute.properties.valueType 的受控枚举
VALUE_TYPES: Tuple[str, ...] = ("Real", "Integer", "Boolean", "String")

#: Requirement.properties.verifyMethod 的受控枚举
VERIFY_METHODS: Tuple[str, ...] = (
    "analysis",
    "inspection",
    "test",
    "simulation",
    "demonstration",
    "review",
)

PRIORITIES: Tuple[str, ...] = ("high", "medium", "low")

#: 不同 kind 允许出现的 properties 子字段（受控白名单）
ALLOWED_PROPS: Dict[str, Tuple[str, ...]] = {
    "PartDefinition": ("description", "isAbstract"),
    "PartUsage": ("typeRef", "quantity", "description"),
    "Requirement": (
        "text",
        "acceptanceCriteria",
        "verifyMethod",
        "rationale",
        "source",
        "priority",
        "description",
    ),
    "ActionDefinition": ("inputs", "outputs", "description"),
    "StateDefinition": ("states", "initial", "transitions", "description"),
    "Attribute": ("valueType", "defaultValue", "unit", "description"),
}

#: Requirement 中被视为「保留字符串字段」的名字；其余字段一律按阈值/参数校验
REQUIREMENT_STRING_FIELDS: Tuple[str, ...] = (
    "text",
    "acceptanceCriteria",
    "verifyMethod",
    "rationale",
    "source",
    "priority",
    "description",
)

#: 各 kind 的必填 properties 子字段
#: 注：Requirement 的 text / acceptanceCriteria 不放在这里——它们由
#: ``_check_requirement`` 统一处理，以便对「缺失」与「空白」给出同一个语义错误码
#: （``E-REQ-NO-TEXT`` / ``E-REQ-NO-ACCEPTANCE``），而不是笼统的 E-PROP-REQUIRED。
REQUIRED_PROPS: Dict[str, Tuple[str, ...]] = {
    "PartDefinition": (),
    "PartUsage": ("typeRef",),
    "Requirement": (),
    "ActionDefinition": ("inputs", "outputs"),
    "StateDefinition": ("states",),
    "Attribute": ("valueType",),
}

_IDENT_RE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_ID_RE_CHARS = _IDENT_RE_CHARS | {"-"}
_ALPHA = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")

#: 生成器会当作关键字渲染的名字，用作软提醒（warning，不是 error）
SYSML_RESERVED_WORDS = frozenset(
    """
    package part def requirement action state attribute item port connect connection doc comment
    import ref in out actor use case objective include subject message end to from about
    specializes subsets redefines abstract alias analysis calc constraint enum exhibit interface
    metadata occurrence perform rendering require satisfy snapshot timeslice transition verify
    view viewpoint concern dependency flow allocation bind
    """.split()
)


# --------------------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------------------


def is_identifier(value: Any) -> bool:
    """``name`` 的合法性：``^[A-Za-z_][A-Za-z0-9_]*$``。

    ``name`` 直接落进 SysML v2 文本当标识符，因此不许出现连字符。
    """
    if not isinstance(value, str) or not value:
        return False
    if value[0] not in _ALPHA:
        return False
    return all(ch in _IDENT_RE_CHARS for ch in value)


def is_id(value: Any) -> bool:
    """``id`` / ``owner`` / ``relations[].target`` / ``typeRef`` 的合法性。

    IR 的 ``id`` 是**模型内的键**（方案 2.3 的示例形如 ``REQ-CRUISE-ENDURANCE``），
    允许连字符；它只活在 JSON 与追溯注释里，不直接当 SysML 标识符用，
    因此比 ``name`` 宽松。
    """
    if not isinstance(value, str) or not value:
        return False
    if value[0] not in _ALPHA:
        return False
    return all(ch in _ID_RE_CHARS for ch in value)


def is_number(value: Any) -> bool:
    """注意：``bool`` 是 ``int`` 的子类，必须显式排除。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def schema_path() -> Path:
    """``mcp-server/schema/sysml-ir-v1.json`` 的绝对路径（跨平台，不含硬编码系统路径）。"""
    here = Path(__file__).resolve().parent
    return here.parent / "schema" / SCHEMA_FILENAME


def load_model(path: Any) -> Dict[str, Any]:
    """读取 IR JSON 文件。UTF-8，跨平台。"""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class _Report:
    """收集 errors / warnings，并记录已报过的 JSON 指针用于跨层去重。"""

    def __init__(self) -> None:
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.pointers: Set[str] = set()

    def error(
        self,
        code: str,
        message: str,
        element: Optional[str] = None,
        pointer: str = "",
    ) -> None:
        self.errors.append(
            {
                "code": code,
                "element": element,
                "message": message,
                "pointer": pointer,
            }
        )
        if pointer:
            self.pointers.add(pointer)

    def warn(
        self,
        code: str,
        message: str,
        element: Optional[str] = None,
        pointer: str = "",
    ) -> None:
        self.warnings.append(
            {
                "code": code,
                "element": element,
                "message": message,
                "pointer": pointer,
            }
        )
        if pointer:
            self.pointers.add(pointer)


# --------------------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------------------


def validate_model_json(
    model: Any,
    use_json_schema: Optional[bool] = None,
) -> Dict[str, Any]:
    """校验 IR JSON。

    :param model: IR JSON（dict，或可被 ``json.loads`` 的 str/bytes）
    :param use_json_schema: ``True`` 强制跑 jsonschema 层；``False`` 跳过；
        ``None``（默认）表示「装了就跑」。jsonschema 缺席时自动降级为纯标准库。
    :return: ``{"ok": bool, "errors": [...], "warnings": [...], "schemaLayer": "..."}``
    """
    model, parse_error = _coerce_model(model)
    report = _Report()

    if parse_error is not None:
        report.error("E-INPUT-NOT-JSON", parse_error)
        return _finish(report, "skipped")

    _check_root(model, report)

    elements = model.get("elements") if isinstance(model, dict) else None
    if not isinstance(elements, list):
        elements = []

    element_by_id: Dict[str, Dict[str, Any]] = {}
    owner_of: Dict[str, Optional[str]] = {}
    names_seen: Dict[Tuple[str, str], str] = {}
    kind_of: Dict[str, str] = {}

    package = model.get("package") if isinstance(model, dict) else None
    valid_owners: Set[str] = {package} if isinstance(package, str) else set()

    # ---- 第一遍：元素骨架、id 唯一、name 唯一、owner 存在 -----------------------------
    for index, element in enumerate(elements):
        pointer = "/elements/%d" % index
        if not isinstance(element, dict):
            report.error(
                "E-ELEMENT-NOT-OBJECT",
                "elements[%d] 不是 JSON 对象，每个元素都必须是对象。" % index,
                None,
                pointer,
            )
            continue

        element_id = element.get("id")
        label = element_id if isinstance(element_id, str) else "<elements[%d]>" % index

        # 必填骨架字段
        for field in ("id", "kind", "name", "owner", "properties"):
            if field not in element:
                report.error(
                    "E-FIELD-MISSING",
                    "元素缺少必填字段 `%s`。" % field,
                    label,
                    pointer + "/" + field,
                )

        if not is_id(element_id):
            report.error(
                "E-ID-INVALID",
                "`id` 必须是非空标识符（^[A-Za-z_][A-Za-z0-9_]*$），实际为 %s。"
                % _repr(element_id),
                label,
                pointer + "/id",
            )
            continue

        if element_id in element_by_id:
            report.error(
                "E-ID-DUP",
                "`id` 全局唯一，但 `%s` 出现了多次（首次出现在 /elements 中更早的位置）。"
                % element_id,
                element_id,
                pointer + "/id",
            )
            continue

        element_by_id[element_id] = element
        valid_owners.add(element_id)

        kind = element.get("kind")
        if kind is None:
            pass
        elif not isinstance(kind, str) or kind not in KINDS:
            report.error(
                "E-KIND-INVALID",
                "`kind` 是受控枚举，不允许自创。允许值：%s；实际为 %s。"
                % ("、".join(KINDS), _repr(kind)),
                element_id,
                pointer + "/kind",
            )
        kind_of[element_id] = kind if isinstance(kind, str) else ""

        name = element.get("name")
        if not is_identifier(name):
            report.error(
                "E-NAME-INVALID",
                "`name` 必须是非空标识符（^[A-Za-z_][A-Za-z0-9_]*$），实际为 %s。"
                % _repr(name),
                element_id,
                pointer + "/name",
            )
        elif isinstance(name, str) and name.lower() in SYSML_RESERVED_WORDS:
            report.warn(
                "W-NAME-RESERVED",
                "`name` = `%s` 与 SysML v2 关键字同名，建议改名以免渲染文本产生歧义。" % name,
                element_id,
                pointer + "/name",
            )

        owner = element.get("owner")
        if not is_id(owner):
            report.error(
                "E-OWNER-INVALID",
                "`owner` 必须是非空标识符（package 名或某元素的 id），实际为 %s。"
                % _repr(owner),
                element_id,
                pointer + "/owner",
            )
        owner_of[element_id] = owner if isinstance(owner, str) else None

        properties = element.get("properties")
        if not isinstance(properties, dict):
            report.error(
                "E-PROP-NOT-OBJECT",
                "`properties` 必须是 JSON 对象，实际为 %s。" % _type_name(properties),
                element_id,
                pointer + "/properties",
            )

        if isinstance(name, str) and isinstance(owner, str):
            key = (owner, name)
            if key in names_seen:
                report.error(
                    "E-NAME-DUP",
                    "同一 owner（`%s`）下 `name` 必须唯一，但 `%s` 与元素 `%s` 重名。"
                    % (owner, name, names_seen[key]),
                    element_id,
                    pointer + "/name",
                )
            else:
                names_seen[key] = element_id

    # ---- 第二遍：owner 必须存在 -------------------------------------------------------
    for element_id, owner in owner_of.items():
        if owner is None:
            continue
        if owner not in valid_owners:
            report.error(
                "E-OWNER-MISSING",
                "`owner` = `%s` 在模型内不存在（既不是 package 名 `%s`，也不是任何元素的 id）。"
                % (owner, package),
                element_id,
                "/elements/%d/owner" % _index_of(elements, element_id),
            )

    # ---- 第三遍：properties 子结构、kind 与子结构匹配 --------------------------------
    for index, element in enumerate(elements):
        if not isinstance(element, dict) or not is_id(element.get("id")):
            continue
        element_id = element["id"]
        kind = element.get("kind")
        properties = element.get("properties")
        if kind not in ALLOWED_PROPS or not isinstance(properties, dict):
            continue
        pointer = "/elements/%d/properties" % index
        _check_properties(element_id, kind, properties, report, pointer, element_by_id)

    # ---- 第四遍：relations 数组与 target 存在 ----------------------------------------
    _check_relations(elements, element_by_id, kind_of, report, package)

    # ---- 第五遍：跨元素可推导的 warning ----------------------------------------------
    _check_warnings(elements, element_by_id, kind_of, report)

    # ---- 第六遍（可选）：JSON Schema 交叉检查 ----------------------------------------
    layer = _run_json_schema(model, report, use_json_schema)

    return _finish(report, layer)


# --------------------------------------------------------------------------------------
# 各遍检查的实现
# --------------------------------------------------------------------------------------


def _coerce_model(model: Any) -> Tuple[Any, Optional[str]]:
    if isinstance(model, (dict, list)):
        return model, None
    if isinstance(model, (str, bytes, bytearray)):
        try:
            return json.loads(model), None
        except Exception as exc:  # noqa: BLE001 - 输入来自 LLM，必须是宽进严出
            return None, "输入不是合法 JSON：%s" % exc
    return model, None


def _check_root(model: Any, report: _Report) -> None:
    if not isinstance(model, dict):
        report.error(
            "E-ROOT-NOT-OBJECT",
            "IR 顶层必须是 JSON 对象（含 schema / package / elements），实际为 %s。"
            % _type_name(model),
        )
        return

    if "schema" not in model:
        report.error("E-FIELD-MISSING", "顶层缺少必填字段 `schema`。", None, "/schema")
    elif model.get("schema") != SCHEMA_ID:
        report.error(
            "E-SCHEMA-VERSION",
            "`schema` 必须是 `%s`，实际为 %s。" % (SCHEMA_ID, _repr(model.get("schema"))),
            None,
            "/schema",
        )

    package = model.get("package")
    if "package" not in model:
        report.error("E-FIELD-MISSING", "顶层缺少必填字段 `package`。", None, "/package")
    elif not is_identifier(package):
        report.error(
            "E-PACKAGE-INVALID",
            "`package` 必须是非空标识符，实际为 %s。" % _repr(package),
            None,
            "/package",
        )

    elements = model.get("elements")
    if "elements" not in model:
        report.error("E-FIELD-MISSING", "顶层缺少必填字段 `elements`。", None, "/elements")
    elif not isinstance(elements, list):
        report.error(
            "E-ELEMENTS-NOT-ARRAY",
            "`elements` 必须是数组，实际为 %s。" % _type_name(elements),
            None,
            "/elements",
        )
    elif not elements:
        report.error("E-ELEMENTS-EMPTY", "`elements` 不能为空数组。", None, "/elements")


def _check_properties(
    element_id: str,
    kind: str,
    props: Dict[str, Any],
    report: _Report,
    pointer: str,
    element_by_id: Dict[str, Dict[str, Any]],
) -> None:
    allowed = ALLOWED_PROPS[kind]

    for field in REQUIRED_PROPS[kind]:
        if field not in props:
            report.error(
                "E-PROP-REQUIRED",
                "%s 的 properties 缺少必填子字段 `%s`。" % (kind, field),
                element_id,
                pointer + "/" + field,
            )
            # 与 JSON Schema 层去重：jsonschema 对 required 缺失报在父对象路径上
            report.pointers.add(pointer)

    # 未知字段（kind 与 properties 子结构不匹配）
    #
    # 例外：Requirement 允许**任意合法的标识符字段名**作为阈值/参数
    # （方案 4.3：「可选数值阈值字段」，如 minEnduranceHours）。
    # 这些字段的类型约束由 _check_requirement 兜住——必须是 number / boolean /
    # {value, unit}，不许写成字符串。
    for field in sorted(props):
        if field in allowed:
            continue
        if kind == "Requirement" and is_identifier(field):
            continue
        report.error(
            "E-PROP-UNKNOWN",
            "%s 的 properties 不允许子字段 `%s`（kind 与 properties 子结构不匹配）。允许：%s。"
            % (kind, field, "、".join(allowed) if allowed else "（无）"),
            element_id,
            pointer + "/" + field,
        )

    # ---- 各 kind 的专用检查 ---------------------------------------------------------
    if kind == "PartDefinition":
        if "description" in props and not isinstance(props["description"], str):
            report.error(
                "E-PROP-TYPE",
                "PartDefinition.description 必须是字符串。",
                element_id,
                pointer + "/description",
            )
        if "isAbstract" in props and not isinstance(props["isAbstract"], bool):
            report.error(
                "E-PROP-TYPE",
                "PartDefinition.isAbstract 必须是布尔值。",
                element_id,
                pointer + "/isAbstract",
            )

    elif kind == "PartUsage":
        type_ref = props.get("typeRef")
        if "typeRef" in props:
            if not is_id(type_ref):
                report.error(
                    "E-PROP-TYPE",
                    "PartUsage.typeRef 必须是非空标识符，实际为 %s。" % _repr(type_ref),
                    element_id,
                    pointer + "/typeRef",
                )
            elif type_ref not in element_by_id:
                report.error(
                    "E-PARTUSAGE-TYPEREF-DANGLING",
                    "PartUsage.typeRef = `%s` 在模型内不存在（悬空引用）。" % type_ref,
                    element_id,
                    pointer + "/typeRef",
                )
            elif element_by_id[type_ref].get("kind") != "PartDefinition":
                report.error(
                    "E-PARTUSAGE-TYPEREF-WRONGKIND",
                    "PartUsage.typeRef = `%s` 指向的元素 kind 是 `%s`，必须指向 PartDefinition。"
                    % (type_ref, element_by_id[type_ref].get("kind")),
                    element_id,
                    pointer + "/typeRef",
                )
        if "quantity" in props and not is_number(props["quantity"]):
            report.error(
                "E-PROP-TYPE",
                "PartUsage.quantity 必须是数字，实际为 %s（%s）。"
                % (_repr(props["quantity"]), _type_name(props["quantity"])),
                element_id,
                pointer + "/quantity",
            )

    elif kind == "Requirement":
        _check_requirement(element_id, props, report, pointer)

    elif kind == "ActionDefinition":
        for field in ("inputs", "outputs"):
            if field not in props:
                continue
            value = props[field]
            if not isinstance(value, list):
                report.error(
                    "E-PROP-TYPE",
                    "ActionDefinition.%s 必须是数组，实际为 %s。" % (field, _type_name(value)),
                    element_id,
                    pointer + "/" + field,
                )
                continue
            seen: Set[str] = set()
            for i, item in enumerate(value):
                item_pointer = "%s/%s/%d" % (pointer, field, i)
                if not isinstance(item, dict):
                    report.error(
                        "E-PROP-TYPE",
                        "ActionDefinition.%s[%d] 必须是对象。" % (field, i),
                        element_id,
                        item_pointer,
                    )
                    continue
                name = item.get("name")
                if not is_identifier(name):
                    report.error(
                        "E-PROP-TYPE",
                        "ActionDefinition.%s[%d].name 必须是非空标识符，实际为 %s。"
                        % (field, i, _repr(name)),
                        element_id,
                        item_pointer + "/name",
                    )
                elif name in seen:
                    report.error(
                        "E-PROP-TYPE",
                        "ActionDefinition.%s 内 name `%s` 重复。" % (field, name),
                        element_id,
                        item_pointer + "/name",
                    )
                else:
                    seen.add(name)
                for sub in ("typeRef", "unit"):
                    if sub in item and not isinstance(item[sub], str):
                        report.error(
                            "E-PROP-TYPE",
                            "ActionDefinition.%s[%d].%s 必须是字符串。" % (field, i, sub),
                            element_id,
                            item_pointer + "/" + sub,
                        )

    elif kind == "StateDefinition":
        _check_state(element_id, props, report, pointer)

    elif kind == "Attribute":
        _check_attribute(element_id, props, report, pointer)


def _check_requirement(
    element_id: str,
    props: Dict[str, Any],
    report: _Report,
    pointer: str,
) -> None:
    for field, code in (
        ("text", "E-REQ-NO-TEXT"),
        ("acceptanceCriteria", "E-REQ-NO-ACCEPTANCE"),
    ):
        value = props.get(field)
        if isinstance(value, str) and value.strip():
            continue
        present = field in props
        message = (
            "Requirement 的 `%s` 不能是空字符串——没有验收判据的要求还不是一条需求。" % field
            if present
            else "Requirement 缺少必填子字段 `%s`——没有验收判据的要求还不是一条需求。" % field
        )
        report.error(code, message, element_id, pointer + "/" + field)
        # 与 JSON Schema 层去重：jsonschema 对 required 缺失报在父对象路径上
        report.pointers.add(pointer)

    if "verifyMethod" in props and props["verifyMethod"] not in VERIFY_METHODS:
        report.error(
            "E-ENUM-INVALID",
            "Requirement.verifyMethod 是受控枚举，允许：%s；实际为 %s。"
            % ("、".join(VERIFY_METHODS), _repr(props["verifyMethod"])),
            element_id,
            pointer + "/verifyMethod",
        )

    if "priority" in props and props["priority"] not in PRIORITIES:
        report.error(
            "E-ENUM-INVALID",
            "Requirement.priority 是受控枚举，允许：%s；实际为 %s。"
            % ("、".join(PRIORITIES), _repr(props["priority"])),
            element_id,
            pointer + "/priority",
        )

    # 除保留字段外，其余字段一律是阈值/参数：必须 number / boolean / {value, unit}
    for field in sorted(props):
        if field in REQUIREMENT_STRING_FIELDS:
            continue
        value = props[field]
        field_pointer = pointer + "/" + field
        if isinstance(value, str):
            report.error(
                "E-PROP-THRESHOLD-STRING",
                "Requirement 的阈值字段 `%s` 被写成了字符串 %s。数值必须写成数字，"
                "单位要么放进 `unit`，要么写成 {\"value\": 4.0, \"unit\": \"h\"}——"
                "否则无法参与计算或导出到仿真。" % (field, _repr(value)),
                element_id,
                field_pointer,
            )
        elif isinstance(value, bool):
            continue
        elif is_number(value):
            continue
        elif isinstance(value, dict):
            if "value" not in value or "unit" not in value:
                report.error(
                    "E-PROP-TYPE",
                    "Requirement 的阈值对象 `%s` 必须同时含 `value`(number) 与 `unit`(string)。"
                    % field,
                    element_id,
                    field_pointer,
                )
            elif not is_number(value["value"]) or not isinstance(value["unit"], str):
                report.error(
                    "E-PROP-TYPE",
                    "Requirement 的阈值对象 `%s` 的 value 必须是数字、unit 必须是字符串。" % field,
                    element_id,
                    field_pointer,
                )
            else:
                report.warn(
                    "W-PROP-UNIT-OBJECT",
                    "阈值字段 `%s` 用了 {value, unit} 对象形式；MVP 渲染器会把它渲染成 "
                    "`attribute %s : Real = ...;` 加单位注释。" % (field, field),
                    element_id,
                    field_pointer,
                )
        else:
            report.error(
                "E-PROP-TYPE",
                "Requirement 的阈值字段 `%s` 类型非法（%s）；只允许 number / boolean / {value, unit}。"
                % (field, _type_name(value)),
                element_id,
                field_pointer,
            )


def _check_state(
    element_id: str,
    props: Dict[str, Any],
    report: _Report,
    pointer: str,
) -> None:
    states = props.get("states")
    state_names: List[str] = []
    if "states" in props:
        if not isinstance(states, list) or not states:
            report.error(
                "E-STATE-STATES-INVALID",
                "StateDefinition.states 必须是非空数组，实际为 %s。" % _type_name(states),
                element_id,
                pointer + "/states",
            )
        else:
            for i, state in enumerate(states):
                if not is_identifier(state):
                    report.error(
                        "E-STATE-STATES-INVALID",
                        "StateDefinition.states[%d] 必须是非空标识符，实际为 %s。"
                        % (i, _repr(state)),
                        element_id,
                        "%s/states/%d" % (pointer, i),
                    )
                elif state in state_names:
                    report.error(
                        "E-STATE-DUP",
                        "StateDefinition.states 中状态名 `%s` 重复。" % state,
                        element_id,
                        "%s/states/%d" % (pointer, i),
                    )
                else:
                    state_names.append(state)

    initial = props.get("initial")
    if "initial" in props:
        if not is_identifier(initial):
            report.error(
                "E-PROP-TYPE",
                "StateDefinition.initial 必须是非空标识符。",
                element_id,
                pointer + "/initial",
            )
        elif state_names and initial not in state_names:
            report.error(
                "E-STATE-INITIAL-NOTFOUND",
                "StateDefinition.initial = `%s` 不在 states 列表内。" % initial,
                element_id,
                pointer + "/initial",
            )

    transitions = props.get("transitions")
    if "transitions" not in props:
        return
    if not isinstance(transitions, list):
        report.error(
            "E-STATE-TRANSITIONS-INVALID",
            "StateDefinition.transitions 必须是数组，实际为 %s。" % _type_name(transitions),
            element_id,
            pointer + "/transitions",
        )
        return

    for i, transition in enumerate(transitions):
        t_pointer = "%s/transitions/%d" % (pointer, i)
        if not isinstance(transition, dict):
            report.error(
                "E-STATE-TRANSITIONS-INVALID",
                "StateDefinition.transitions[%d] 必须是对象。" % i,
                element_id,
                t_pointer,
            )
            continue
        for endpoint in ("from", "to"):
            value = transition.get(endpoint)
            if not is_identifier(value):
                report.error(
                    "E-STATE-TRANSITIONS-INVALID",
                    "StateDefinition.transitions[%d].%s 必须是非空标识符，实际为 %s。"
                    % (i, endpoint, _repr(value)),
                    element_id,
                    t_pointer + "/" + endpoint,
                )
            elif state_names and value not in state_names:
                report.error(
                    "E-STATE-TRANSITION-ENDPOINT",
                    "StateDefinition.transitions[%d].%s = `%s` 不在 states 列表内（未声明的状态）。"
                    % (i, endpoint, value),
                    element_id,
                    t_pointer + "/" + endpoint,
                )
        for sub in ("trigger", "guard"):
            if sub in transition and not isinstance(transition[sub], str):
                report.error(
                    "E-PROP-TYPE",
                    "StateDefinition.transitions[%d].%s 必须是字符串。" % (i, sub),
                    element_id,
                    t_pointer + "/" + sub,
                )


def _check_attribute(
    element_id: str,
    props: Dict[str, Any],
    report: _Report,
    pointer: str,
) -> None:
    value_type = props.get("valueType")
    if "valueType" in props and value_type not in VALUE_TYPES:
        report.error(
            "E-ENUM-INVALID",
            "Attribute.valueType 是受控枚举，允许：%s；实际为 %s。"
            % ("、".join(VALUE_TYPES), _repr(value_type)),
            element_id,
            pointer + "/valueType",
        )
    if "unit" in props and (not isinstance(props["unit"], str) or not props["unit"].strip()):
        report.error(
            "E-PROP-TYPE",
            "Attribute.unit 必须是非空字符串（单位单独成字段，不写进数值字符串）。",
            element_id,
            pointer + "/unit",
        )

    if "defaultValue" not in props or value_type not in VALUE_TYPES:
        return
    default = props["defaultValue"]
    ok = True
    if value_type == "Real":
        ok = is_number(default)
    elif value_type == "Integer":
        ok = is_integer(default)
    elif value_type == "Boolean":
        ok = isinstance(default, bool)
    elif value_type == "String":
        ok = isinstance(default, str)
    if not ok:
        report.error(
            "E-ATTR-DEFAULT-TYPE",
            "Attribute.defaultValue 与 valueType=`%s` 不匹配：实际为 %s（%s）。"
            % (value_type, _repr(default), _type_name(default)),
            element_id,
            pointer + "/defaultValue",
        )


def _check_relations(
    elements: List[Any],
    element_by_id: Dict[str, Dict[str, Any]],
    kind_of: Dict[str, str],
    report: _Report,
    package: Any,
) -> None:
    for index, element in enumerate(elements):
        if not isinstance(element, dict) or not is_id(element.get("id")):
            continue
        element_id = element["id"]
        if "relations" not in element:
            continue
        relations = element["relations"]
        pointer = "/elements/%d/relations" % index
        if not isinstance(relations, list):
            report.error(
                "E-REL-NOT-ARRAY",
                "`relations` 必须是数组，实际为 %s。" % _type_name(relations),
                element_id,
                pointer,
            )
            continue

        for i, relation in enumerate(relations):
            r_pointer = "%s/%d" % (pointer, i)
            if not isinstance(relation, dict):
                report.error(
                    "E-REL-ITEM-NOT-OBJECT",
                    "relations[%d] 必须是对象，含 type/target/rationale。" % i,
                    element_id,
                    r_pointer,
                )
                continue
            for field in ("type", "target", "rationale"):
                if field not in relation:
                    report.error(
                        "E-REL-FIELD-MISSING",
                        "relations[%d] 缺少必填字段 `%s`。" % (i, field),
                        element_id,
                        r_pointer + "/" + field,
                    )

            rel_type = relation.get("type")
            if "type" in relation and rel_type not in RELATION_TYPES:
                report.error(
                    "E-REL-TYPE-INVALID",
                    "relations[%d].type 是受控枚举，不允许自创。允许：%s；实际为 %s。"
                    % (i, "、".join(RELATION_TYPES), _repr(rel_type)),
                    element_id,
                    r_pointer + "/type",
                )

            target = relation.get("target")
            if "target" in relation:
                if not is_id(target):
                    report.error(
                        "E-REL-TARGET-INVALID",
                        "relations[%d].target 必须是非空标识符，实际为 %s。"
                        % (i, _repr(target)),
                        element_id,
                        r_pointer + "/target",
                    )
                elif target not in element_by_id:
                    report.error(
                        "E-REL-TARGET-DANGLING",
                        "relations[%d].target = `%s` 在模型内不存在（悬空引用）；"
                        "relations.target 必须指向模型内已存在的元素 id。" % (i, target),
                        element_id,
                        r_pointer + "/target",
                    )
                elif target == element_id:
                    report.warn(
                        "W-REL-SELF",
                        "relations[%d] 的 target 指向自己（`%s`），确认是否为笔误。" % (i, target),
                        element_id,
                        r_pointer + "/target",
                    )
                elif rel_type == "connects" and kind_of.get(target) not in (
                    "PartDefinition",
                    "PartUsage",
                ):
                    owner_kind = kind_of.get(element_id)
                    if owner_kind in ("PartDefinition", "PartUsage"):
                        report.warn(
                            "W-CONNECTS-NON-PART",
                            "connects 关系的目标 `%s` 的 kind 是 `%s`，不是结构元素"
                            "（PartDefinition/PartUsage）。" % (target, kind_of.get(target)),
                            element_id,
                            r_pointer + "/target",
                        )

            rationale = relation.get("rationale")
            if "rationale" in relation:
                if not isinstance(rationale, str) or not rationale.strip():
                    report.error(
                        "E-REL-NO-RATIONALE",
                        "relations[%d].rationale 必须是非空字符串——关系必须说明理由。"
                        % i,
                        element_id,
                        r_pointer + "/rationale",
                    )


def _check_warnings(
    elements: List[Any],
    element_by_id: Dict[str, Dict[str, Any]],
    kind_of: Dict[str, str],
    report: _Report,
) -> None:
    referenced: Set[str] = set()
    for element in elements:
        if not isinstance(element, dict) or not is_id(element.get("id")):
            continue
        for relation in element.get("relations") or []:
            if isinstance(relation, dict) and is_id(relation.get("target")):
                referenced.add(relation["target"])
        props = element.get("properties")
        if isinstance(props, dict) and is_id(props.get("typeRef")):
            referenced.add(props["typeRef"])

    used_as_type_ref: Set[str] = set()

    for index, element in enumerate(elements):
        if not isinstance(element, dict) or not is_id(element.get("id")):
            continue
        element_id = element["id"]
        kind = kind_of.get(element_id, "")
        props = element.get("properties")
        props = props if isinstance(props, dict) else {}
        relations = element.get("relations") or []
        rel_types = {
            r.get("type") for r in relations if isinstance(r, dict) and isinstance(r.get("type"), str)
        }
        pointer = "/elements/%d" % index

        if kind == "Requirement":
            if "verifyMethod" in props:
                has_verify = "verifies" in rel_types or any(
                    isinstance(r, dict)
                    and r.get("type") == "verifies"
                    and r.get("target") == element_id
                    for other in elements
                    if isinstance(other, dict)
                    for r in (other.get("relations") or [])
                )
                if not has_verify:
                    report.warn(
                        "W-REQ-NO-VERIFY",
                        "该需求标注 verifyMethod=%s，但尚未建立指向验证用例（仿真/试验）的 "
                        "verifies 关系。" % props.get("verifyMethod"),
                        element_id,
                        pointer + "/properties/verifyMethod",
                    )
            if "satisfiedBy" not in rel_types:
                report.warn(
                    "W-REQ-NO-SATISFY",
                    "该需求没有 satisfiedBy 关系（没有任何结构或功能声明满足它）。",
                    element_id,
                    pointer,
                )

        if kind == "PartUsage" and is_id(props.get("typeRef")):
            used_as_type_ref.add(props["typeRef"])

        has_relations = bool(rel_types)
        if kind == "PartDefinition" and element_id not in referenced and not has_relations:
            report.warn(
                "W-ELEMENT-ORPHAN",
                "该元素既没有被任何元素引用，自身也没有 relations——可能是孤立元素。",
                element_id,
                pointer,
            )

    for element_id, kind in sorted(kind_of.items()):
        if kind == "PartDefinition" and element_id not in used_as_type_ref:
            report.warn(
                "W-PARTDEF-UNUSED",
                "PartDefinition `%s` 没有被任何 PartUsage.typeRef 使用；MVP 的 IR 要求"
                "结构定义最终由 PartUsage 实例化。" % element_id,
                element_id,
            )


# --------------------------------------------------------------------------------------
# 可选的 JSON Schema 交叉检查层
# --------------------------------------------------------------------------------------


def _run_json_schema(model: Any, report: _Report, use_json_schema: Optional[bool]) -> str:
    if use_json_schema is False:
        return "skipped"
    if os.environ.get("SYSML_IR_USE_JSONSCHEMA") == "0":
        return "skipped"
    try:
        import jsonschema  # type: ignore
    except Exception:  # noqa: BLE001 - 第三方依赖缺席时静默降级
        return "unavailable"

    path = schema_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        report.warn(
            "W-SCHEMA-UNREADABLE",
            "无法读取 JSON Schema 文件 %s：%s（已跳过该层）。" % (path, exc),
        )
        return "unreadable"

    try:
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
        validator = validator_cls(schema)
    except Exception as exc:  # noqa: BLE001
        report.warn("W-SCHEMA-INVALID", "JSON Schema 自身校验失败：%s" % exc)
        return "invalid"

    added = 0
    for error in sorted(validator.iter_errors(model), key=lambda e: list(e.absolute_path)):
        pointer = "/" + "/".join(str(p) for p in error.absolute_path)
        if pointer in report.pointers:
            continue
        element = None
        if len(error.absolute_path) >= 2 and error.absolute_path[0] == "elements":
            index = error.absolute_path[1]
            elements = model.get("elements") if isinstance(model, dict) else None
            if isinstance(elements, list) and isinstance(index, int) and 0 <= index < len(elements):
                candidate = elements[index]
                if isinstance(candidate, dict) and isinstance(candidate.get("id"), str):
                    element = candidate["id"]
        report.error("E-SCHEMA", "JSON Schema（%s）：%s" % (SCHEMA_ID, error.message), element, pointer)
        added += 1
    return "ok(+%d)" % added


# --------------------------------------------------------------------------------------
# 收尾
# --------------------------------------------------------------------------------------


def _finish(report: _Report, layer: str) -> Dict[str, Any]:
    return {
        "ok": not report.errors,
        "errors": report.errors,
        "warnings": report.warnings,
        "schemaLayer": layer,
        "counts": {"errors": len(report.errors), "warnings": len(report.warnings)},
    }


def _index_of(elements: List[Any], element_id: str) -> int:
    for i, element in enumerate(elements):
        if isinstance(element, dict) and element.get("id") == element_id:
            return i
    return -1


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


def _iter_errors(result: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    return result.get("errors", [])


# --------------------------------------------------------------------------------------
# CLI：python -m tools.validator <ir.json>
# --------------------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) != 2:
        print("用法：python -m tools.validator <ir.json>")
        raise SystemExit(2)
    outcome = validate_model_json(load_model(sys.argv[1]))
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    raise SystemExit(0 if outcome["ok"] else 1)
