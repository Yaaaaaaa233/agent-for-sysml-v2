"""``export_simulink`` —— 把 IR 里的参数与约束导出给仿真侧（Simulink / MATLAB）。

定位（技术方案 5.2 第 7 项 / 9.2 的 T10）：模型是唯一事实来源，仿真侧不该手抄参数。
本工具从 IR JSON 确定性地抽出三类可消费内容：

===============  ================================================================
scope            导出内容
===============  ================================================================
``attributes``   每个 ``Attribute`` 一行参数（值、类型、单位、所属路径）
``constraints``  每个 ``Constraint`` 一行公式（``expression`` + ``parameters``）
``requirements`` 每个 ``Requirement`` 的数值阈值（number / boolean / ``{value,unit}``）
``all``          以上三类全导出（默认）
===============  ================================================================

设计原则与 ``generator`` / ``query`` 保持一致：

1. **纯函数、确定性**：不读写文件、不改传入模型；行按 ``(path, name, kind, id)``
   稳定排序，同一输入必得逐字节相同的 ``content``。
2. **不重复校验器**：导出不是第二道 ``validate_model_json``。IR 有结构问题时
   （缺 ``valueType``、缺 ``expression``、阈值写成字符串……）不抛异常、不中断，
   而是**优雅降级**并把原因写进 ``notes``，让调用方看到「哪些行不可信」。
   这样也保证对**未知 kind 保持通用**：二期新增的 ``Constraint`` 不要求导出器
   跟着改白名单，遇到不认识的 kind 直接忽略即可。
3. **诚实标注**：参数值来自 IR 的 ``defaultValue``，可能仍是占位值；导出的
   ``notes`` 与配套样例文档都必须显式说明这一点，不能把导出的数字当成实测结论。
4. **不出现真实项目文件名**：消费示例只用 ``params.csv`` 这类中性占位名。

返回结构（后续 MCP 注册按此对接，勿改名/改形状）::

    {"ok": bool, "content": str, "rows": list, "notes": list, "errors": list}

``rows`` 里三种行的字段：

- ``Attribute``：``path / name / valueType / unit / defaultValue / kind / id``
- ``Constraint``：``path / name / expression / parameters / kind / id``
- ``RequirementThreshold``：``path / name / valueType / unit / defaultValue / kind / id``

CSV / Markdown 的列固定为 ``path,name,valueType,unit,defaultValue,kind,id,extra``：
``Constraint`` 行的公式放 ``defaultValue`` 列（该行此列语义是公式而非默认值），
参数名列表放 ``extra`` 列（JSON）；``RequirementThreshold`` 行在 ``extra`` 列标注
「需求阈值，非部件参数」。
"""

from __future__ import annotations

import csv
import io
import json
import sys
from typing import Any, Dict, List, Optional, Tuple

#: 支持的输出格式
FORMATS: Tuple[str, ...] = ("csv", "json", "md")

#: 支持的导出范围
SCOPES: Tuple[str, ...] = ("all", "attributes", "constraints", "requirements")

#: CSV 固定表头（MATLAB ``readtable`` 直接按此取列；不要随模型变化）
CSV_HEADER: Tuple[str, ...] = (
    "path",
    "name",
    "valueType",
    "unit",
    "defaultValue",
    "kind",
    "id",
    "extra",
)

#: Requirement 里的保留字符串字段；其余自定义字段才视为阈值/参数
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

#: 所有格式都会带上的诚实标注：导出值 ≠ 实测值
PLACEHOLDER_NOTE = (
    "参数值直接取自 IR 的 defaultValue，可能仍是占位值（非实测结论）；"
    "用于仿真前须与选型数据或实测数据核对。"
)


def export_simulink(model: dict, fmt: str = "csv", scope: str = "all") -> dict:
    """把 IR JSON 的参数与约束导出成仿真侧可消费的参数表 / 公式清单。

    :param model: IR JSON（dict；也接受 JSON 字符串，便于 MCP 客户端透传）
    :param fmt: ``"csv"``（默认，UTF-8 BOM + 固定表头）、``"json"``、``"md"``
    :param scope: ``"all"``（默认）/ ``"attributes"`` / ``"constraints"`` / ``"requirements"``
    :return: ``{"ok", "content", "rows", "notes", "errors"}``
    """
    errors: List[Dict[str, Any]] = []
    if fmt not in FORMATS:
        errors.append(
            _error(
                "E-EXPORT-FMT",
                None,
                "fmt 必须是 %s 之一，实际为 %r。" % ("、".join(FORMATS), fmt),
            )
        )
    if scope not in SCOPES:
        errors.append(
            _error(
                "E-EXPORT-SCOPE",
                None,
                "scope 必须是 %s 之一，实际为 %r。" % ("、".join(SCOPES), scope),
            )
        )
    if errors:
        return _result(False, "", [], [], errors)

    model, parse_error = _coerce_model(model)
    if parse_error is not None:
        return _result(False, "", [], [], [_error("E-EXPORT-INPUT", None, parse_error)])

    notes: List[str] = []
    elements = model.get("elements")
    if not isinstance(elements, list):
        notes.append("模型没有 `elements` 数组（或类型不是数组），按空模型导出 0 行。")
        elements = []
    else:
        skipped = [i for i, item in enumerate(elements) if not isinstance(item, dict)]
        if skipped:
            notes.append(
                "elements 中有 %d 个元素不是 JSON 对象，已跳过（索引：%s）。"
                % (len(skipped), "、".join(str(i) for i in skipped[:8]))
            )
        elements = [item for item in elements if isinstance(item, dict)]
        missing_id = [
            i
            for i, item in enumerate(elements)
            if not isinstance(item.get("id"), str) or not item.get("id")
        ]
        if missing_id:
            notes.append(
                "elements 中有 %d 个元素缺少有效 `id`，已跳过（索引：%s）。"
                % (len(missing_id), "、".join(str(i) for i in missing_id[:8]))
            )

    package = model.get("package")
    if not isinstance(package, str) or not package:
        notes.append("模型缺少 `package`，路径最外层按空包名处理。")
        package = ""

    index = _Index(elements, package)
    rows: List[Dict[str, Any]] = []
    if scope in ("all", "attributes"):
        rows.extend(index.attribute_rows(notes))
    if scope in ("all", "constraints"):
        rows.extend(index.constraint_rows(notes))
    if scope in ("all", "requirements"):
        rows.extend(index.requirement_rows(notes))

    rows.sort(key=_row_sort_key)
    notes.extend(_consumption_notes(fmt, scope))
    content = _render(rows, notes, fmt)
    return _result(True, content, rows, notes, [])


# --------------------------------------------------------------------------------------
# 模型索引：owner 链路径、三类行的抽取
# --------------------------------------------------------------------------------------


class _Index:
    """元素索引与行抽取。所有遍历都按元素 id 排序，保证输出顺序与输入顺序无关。"""

    def __init__(self, elements: List[Dict[str, Any]], package: str) -> None:
        self.package = package
        self.by_id: Dict[str, Dict[str, Any]] = {}
        for element in elements:
            element_id = element.get("id")
            if isinstance(element_id, str) and element_id and element_id not in self.by_id:
                self.by_id[element_id] = element

    # -- 路径 -------------------------------------------------------------------------

    def path_of(
        self,
        element: Dict[str, Any],
        notes: List[str],
        include_self: bool = False,
    ) -> str:
        """元素所在的 owner 链（含 package），用 ``.`` 连接。

        例：属性 ``batteryCapacityWh`` 的 owner 是 ``PART-BATTERY-PACK``（name
        ``BatteryPack``），后者 owner 是 package ``CoaxialOctoRotor``，
        于是路径为 ``CoaxialOctoRotor.BatteryPack``。

        ``include_self=True`` 时把元素自己的 name 也放进路径——需求阈值字段的
        「所有者」是那条需求，所以阈值行的 path 会形如
        ``CoaxialOctoRotor.CruiseEndurance``。
        """
        element_id = element.get("id")
        segments: List[str] = []
        if include_self:
            segments.append(_name_of(element))

        owner = element.get("owner")
        seen: set = set()
        while True:
            if not isinstance(owner, str) or not owner:
                if not segments:
                    notes.append(
                        "元素 `%s` 没有可解析的 owner 链，path 按空字符串导出。" % element_id
                    )
                break
            if owner == self.package:
                segments.append(self.package)
                break
            if owner in seen:
                notes.append(
                    "元素 `%s` 的 owner 链存在循环（在 `%s` 处），path 按已解析部分导出。"
                    % (element_id, owner)
                )
                break
            seen.add(owner)
            node = self.by_id.get(owner)
            if node is None:
                notes.append(
                    "元素 `%s` 的 owner `%s` 不在模型内，path 按原值保留。" % (element_id, owner)
                )
                segments.append(owner)
                break
            segments.append(_name_of(node))
            owner = node.get("owner")

        return ".".join(reversed(segments))

    # -- Attribute --------------------------------------------------------------------

    def attribute_rows(self, notes: List[str]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        missing_type: List[str] = []
        missing_default: List[str] = []

        for element_id in sorted(self.by_id):
            element = self.by_id[element_id]
            if element.get("kind") != "Attribute":
                continue
            props = element.get("properties")
            props = props if isinstance(props, dict) else {}

            value_type = props.get("valueType")
            if not isinstance(value_type, str) or not value_type:
                value_type = ""
                missing_type.append(element_id)

            unit = props.get("unit")
            unit = unit if isinstance(unit, str) else ""

            if "defaultValue" in props:
                default_value = props["defaultValue"]
            else:
                default_value = ""
                missing_default.append(element_id)

            rows.append(
                {
                    "path": self.path_of(element, notes),
                    "name": _name_of(element),
                    "valueType": value_type,
                    "unit": unit,
                    "defaultValue": default_value,
                    "kind": "Attribute",
                    "id": element_id,
                }
            )

        if missing_type:
            notes.append(
                "Attribute 缺少 valueType，已按空字符串导出：%s。" % _brief_ids(missing_type)
            )
        if missing_default:
            notes.append(
                "Attribute 缺少 defaultValue，已按空字符串导出（CSV 为空单元格）：%s。"
                % _brief_ids(missing_default)
            )
        return rows

    # -- Constraint -------------------------------------------------------------------

    def constraint_rows(self, notes: List[str]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []

        for element_id in sorted(self.by_id):
            element = self.by_id[element_id]
            if element.get("kind") != "Constraint":
                continue
            props = element.get("properties")
            props = props if isinstance(props, dict) else {}

            expression = props.get("expression")
            if not isinstance(expression, str) or not expression:
                expression = ""
                notes.append(
                    "Constraint `%s` 缺少非空 `expression`，已导出空公式行（请补 IR 后重导）。"
                    % element_id
                )

            parameters = self.parameters_of(element_id, props.get("parameters"), notes)
            rows.append(
                {
                    "path": self.path_of(element, notes),
                    "name": _name_of(element),
                    "expression": expression,
                    "parameters": parameters,
                    "kind": "Constraint",
                    "id": element_id,
                }
            )
        return rows

    def parameters_of(
        self,
        element_id: str,
        raw: Any,
        notes: List[str],
    ) -> List[str]:
        """把 ``parameters`` 里的元素 id 引用解析成 name 列表；解析不到就保留原值。"""
        if raw is None:
            notes.append(
                "Constraint `%s` 缺少 `parameters`，参数列表按空导出。" % element_id
            )
            return []
        if isinstance(raw, str):
            items: List[Any] = [raw]
        elif isinstance(raw, list):
            items = raw
        else:
            notes.append(
                "Constraint `%s` 的 `parameters` 既不是数组也不是字符串，参数列表按空导出。"
                % element_id
            )
            return []

        resolved: List[str] = []
        unknown: List[str] = []
        wrong_kind: List[str] = []
        if not items:
            notes.append(
                "Constraint `%s` 的 `parameters` 为空，参数列表按空导出。" % element_id
            )
        for item in items:
            ref = item
            if isinstance(item, dict):
                ref = item.get("id") if isinstance(item.get("id"), str) else item.get("name")
            if not isinstance(ref, str) or not ref:
                notes.append(
                    "Constraint `%s` 的 parameters 中有非字符串项，已跳过。" % element_id
                )
                continue
            target = self.by_id.get(ref)
            if target is None:
                resolved.append(ref)
                unknown.append(ref)
            else:
                resolved.append(_name_of(target))
                if target.get("kind") != "Attribute":
                    wrong_kind.append(ref)

        if unknown:
            notes.append(
                "Constraint `%s` 的参数引用无法解析为模型内元素 id，按原值保留：%s。"
                % (element_id, _brief_ids(unknown))
            )
        if wrong_kind:
            notes.append(
                "Constraint `%s` 的参数引用了非 Attribute 元素，已按原 name 保留：%s。"
                % (element_id, _brief_ids(wrong_kind))
            )
        return resolved

    # -- Requirement 阈值 --------------------------------------------------------------

    def requirement_rows(self, notes: List[str]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        skipped: List[str] = []
        missing_unit: List[str] = []

        for element_id in sorted(self.by_id):
            element = self.by_id[element_id]
            if element.get("kind") != "Requirement":
                continue
            props = element.get("properties")
            props = props if isinstance(props, dict) else {}
            path = self.path_of(element, notes, include_self=True)
            name = _name_of(element)

            for field in sorted(props):
                if field in REQUIREMENT_STRING_FIELDS:
                    continue
                parsed = _threshold_of(props[field])
                if parsed is None:
                    skipped.append("%s.%s" % (name, field))
                    continue
                value_type, unit, value, unit_ok = parsed
                if not unit_ok:
                    missing_unit.append("%s.%s" % (name, field))
                rows.append(
                    {
                        "path": path,
                        "name": field,
                        "valueType": value_type,
                        "unit": unit,
                        "defaultValue": value,
                        "kind": "RequirementThreshold",
                        "id": element_id,
                    }
                )

        if missing_unit:
            notes.append(
                "以下 Requirement 阈值用 {value, unit} 表达但缺少 unit，unit 列按空导出：%s。"
                % _brief_ids(missing_unit)
            )
        if skipped:
            notes.append(
                "以下 Requirement 自定义字段不是 number/boolean/{value, unit}，已跳过"
                "（数值请写成数字并单独给 unit）：%s。"
                % _brief_ids(skipped)
            )
        if rows:
            notes.append(
                "RequirementThreshold 行是需求阈值，非部件参数；应作为仿真判据 / 校核条件使用。"
            )
        return rows


# --------------------------------------------------------------------------------------
# 行渲染：csv / json / md
# --------------------------------------------------------------------------------------


def _render(rows: List[Dict[str, Any]], notes: List[str], fmt: str) -> str:
    if fmt == "csv":
        return _render_csv(rows)
    if fmt == "json":
        payload = {"rows": rows, "notes": notes}
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return _render_md(rows)


def _render_csv(rows: List[Dict[str, Any]]) -> str:
    """UTF-8 BOM + CRLF + 固定表头；字段含逗号/引号/换行时由 csv 模块转义。"""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow(_tabular_cells(row))
    return "\ufeff" + buffer.getvalue()


def _render_md(rows: List[Dict[str, Any]]) -> str:
    lines = [
        "| " + " | ".join(CSV_HEADER) + " |",
        "| " + " | ".join("---" for _ in CSV_HEADER) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(cell) for cell in _tabular_cells(row)) + " |")
    return "\n".join(lines) + "\n"


def _tabular_cells(row: Dict[str, Any]) -> List[str]:
    """把一行映射到固定 8 列；行里没有的字段导出为空单元格。"""
    kind = row.get("kind")
    extra = ""
    default_value = row.get("defaultValue")
    if kind == "Constraint":
        # 固定表头里没有 expression 列：公式放在 defaultValue 列（该行此列语义是公式），
        # 参数名列表放 extra 列，保证 CSV / Markdown 只有一套列定义。
        default_value = row.get("expression")
        extra = json.dumps(
            {"parameters": row.get("parameters") or []},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    elif kind == "RequirementThreshold":
        extra = json.dumps(
            {"note": "需求阈值，非部件参数"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return [
        _fmt_cell(row.get("path")),
        _fmt_cell(row.get("name")),
        _fmt_cell(row.get("valueType")),
        _fmt_cell(row.get("unit")),
        _fmt_cell(default_value),
        _fmt_cell(kind),
        _fmt_cell(row.get("id")),
        extra,
    ]


def _md_cell(value: Any) -> str:
    text = _fmt_cell(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return text


# --------------------------------------------------------------------------------------
# 格式化辅助（全部确定性）
# --------------------------------------------------------------------------------------


def _fmt_cell(value: Any) -> str:
    """单元格/JSON 值的稳定文本化：布尔小写、整数原样、浮点保留类型特征。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return repr(value)
        if value == int(value) and abs(value) < 1e16:
            return "%.1f" % value
        return repr(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _threshold_of(value: Any) -> Optional[Tuple[str, str, Any, bool]]:
    """把 Requirement 的自定义字段解析成 ``(valueType, unit, defaultValue, unit_ok)``。

    只接受 number / boolean / ``{value, unit}``（与 Schema 的 patternProperties 一致）；
    其余类型返回 ``None``，由调用方记入 notes 后跳过。
    """
    if isinstance(value, bool):
        return ("Boolean", "", value, True)
    if isinstance(value, int):
        return ("Integer", "", value, True)
    if isinstance(value, float):
        return ("Real", "", value, True)
    if isinstance(value, dict):
        inner = value.get("value")
        unit = value.get("unit")
        unit_ok = isinstance(unit, str) and bool(unit)
        unit = unit if unit_ok else ""
        if isinstance(inner, bool):
            return ("Boolean", unit, inner, unit_ok)
        if isinstance(inner, int):
            return ("Integer", unit, inner, unit_ok)
        if isinstance(inner, float):
            return ("Real", unit, inner, unit_ok)
    return None


def _row_sort_key(row: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (
        str(row.get("path") or ""),
        str(row.get("name") or ""),
        str(row.get("kind") or ""),
        str(row.get("id") or ""),
    )


def _name_of(element: Dict[str, Any]) -> str:
    name = element.get("name")
    if isinstance(name, str) and name:
        return name
    element_id = element.get("id")
    return element_id if isinstance(element_id, str) else ""


def _brief_ids(values: List[str], limit: int = 8) -> str:
    shown = "、".join(values[:limit])
    if len(values) > limit:
        shown += " 等 %d 项" % len(values)
    return shown


def _error(code: str, element: Optional[str], message: str) -> Dict[str, Any]:
    return {"code": code, "element": element, "message": message}


def _result(
    ok: bool,
    content: str,
    rows: List[Dict[str, Any]],
    notes: List[str],
    errors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "ok": ok,
        "content": content,
        "rows": rows,
        "notes": notes,
        "errors": errors,
    }


def _coerce_model(model: Any) -> Tuple[Any, Optional[str]]:
    if isinstance(model, (str, bytes, bytearray)):
        try:
            model = json.loads(model)
        except Exception as exc:  # noqa: BLE001
            return None, "输入不是合法 JSON：%s" % exc
    if not isinstance(model, dict):
        return None, "IR 顶层必须是 JSON 对象，实际为 %s。" % type(model).__name__
    return model, None


def _consumption_notes(fmt: str, scope: str) -> List[str]:
    """仿真侧消费提示。**只用中性占位文件名**，不写任何真实项目/模型文件名。"""
    notes = [
        "导出范围 scope=%s，格式 fmt=%s。" % (scope, fmt),
        PLACEHOLDER_NOTE,
    ]
    if fmt == "csv":
        notes.append(
            "CSV 为 UTF-8 BOM + CRLF、表头固定（%s）；MATLAB 可用 "
            "`readtable('params.csv', 'TextType', 'string')` 直接读取"
            "（文件名仅作示例）。" % ",".join(CSV_HEADER)
        )
        notes.append(
            "Simulink 侧建议逐行装配 `Simulink.Parameter`：Value 取 defaultValue，"
            "Unit 取 unit，Description 由 path 与 name 拼出，再统一加载到仿真工作区。"
        )
        notes.append(
            "Constraint 行的 defaultValue 列是公式文本，extra 列是 "
            '{"parameters":[...]} 的 JSON；公式行不能直接当参数赋值，'
            "需在仿真侧按 expression 建立计算或约束。"
        )
    elif fmt == "json":
        notes.append(
            'content 是 {"rows": [...], "notes": [...]} 的 JSON 字符串；'
            "MATLAB 可用 `jsondecode`、Python 可用 `json.loads` 还原。"
        )
        notes.append(
            "Constraint 行保留 expression / parameters 字段；"
            "RequirementThreshold 行用 defaultValue 与 unit 表示阈值。"
            "在 Simulink 侧建议把 Attribute 行装配为 `Simulink.Parameter`，"
            "公式行与阈值行分别作为约束和判据使用。"
        )
    else:
        notes.append(
            "Markdown 表供人工评审与文档引用；机器消费请改用 fmt=\"csv\" 或 fmt=\"json\"。"
        )
        notes.append(
            "单元格中的换行以 `<br>` 表示、`|` 已转义；Constraint 行的公式在 "
            "defaultValue 列，参数列表在 extra 列。"
        )
    return notes


# --------------------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import argparse

    from .validator import load_model

    parser = argparse.ArgumentParser(
        description="把 IR JSON 导出为仿真侧参数表 / 公式清单。"
    )
    parser.add_argument("ir", help="IR JSON 文件路径")
    parser.add_argument("--fmt", default="csv", choices=FORMATS)
    parser.add_argument("--scope", default="all", choices=SCOPES)
    options = parser.parse_args()

    outcome = export_simulink(load_model(options.ir), fmt=options.fmt, scope=options.scope)
    if outcome["ok"]:
        sys.stdout.write(outcome["content"])
        for note in outcome["notes"]:
            print("[note] %s" % note, file=sys.stderr)
    else:
        print(json.dumps(outcome["errors"], ensure_ascii=False, indent=2), file=sys.stderr)
    raise SystemExit(0 if outcome["ok"] else 1)
