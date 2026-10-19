"""``timeline`` —— 模型修订历史（``sysml-viz-history/v1``）→ 建模过程 SVG。

定位（Q2「图形化侧边栏」的过程证据层）：DSH 插件把每次模型变更写成
``<workspace>/.sysml-viz/history/index.json`` 与逐级完整 IR 快照；本工具只读这些文件，
生成一张「系统如何一步步建模完善」的确定性 SVG。IR 仍是唯一事实源，历史目录不被修改。

输入目录（已定契约，不在此处重新定义）::

    .sysml-viz/history/
      index.json                       # schema=sysml-viz-history/v1，steps 从 0 连续
      step-0000-98713da0.ir.json       # 每一步当时的完整 IR（schema=sysml-ir/v1）
      step-0001-b6d3b3a1.ir.json
      ...

核心 API::

    load_history(history_dir) -> dict
        # 读 index.json 并做基本校验；失败抛 TimelineError(code, message)
    build_timeline(history, snapshots) -> dict
        # 纯函数：steps / elements / tree / firstSeen / summary / colors
    render_svg(timeline, opts=None) -> str
        # 确定性 SVG；opts = {title, subtitle, generated_at, width}
    export_timeline(history_dir, out_path=None, *, title=None, generated_at=None) -> dict
        # 永不抛异常；返回 {ok, schema, svgPath, summary, steps, errors, warnings}
    main(argv=None) -> int

``build_timeline`` 的 ``steps`` 与 index 的 steps 同序；``elements`` 只含**最终快照**里的
元素（不是 index 元数据），按 ``validator.KINDS`` 的 kind 顺序再按 id 升序；``tree`` 是
最终模型的 owner 层级（owner 是包名 / 找不到 / 成环时挂到根）；``firstSeen`` 是
``{elementId: firstSeq}``；``colors`` 与 steps 等长，是每一步的颜色（基线固定灰）。
真实会话日志重建的 index 若带可选 ``turn`` / ``note``，steps 记录里会原样透传，图例优先
显示「第 N 轮」。

降级与错误码：

==========================  ============================================================
``E-HISTORY-NOT-FOUND``     目录或 ``index.json`` 不存在
``E-HISTORY-SCHEMA``        index 不是合法 JSON / schema 不对 / steps 不是数组 / seq 不连续
``E-NO-STEPS``              steps 为空数组
``W-SNAPSHOT-MISSING``      某步快照文件缺失；回退到相邻可用快照，仍出图
``W-SNAPSHOT-PARSE``        某步快照坏 JSON / 无 ``elements``；回退到上一个有效快照
``E-WRITE``                 SVG 写出失败（``ok=false``）
==========================  ============================================================

SVG 四块：页眉、左侧最终系统生长树、右侧步骤图例、底部元素数生长曲线；字体只使用
系统字体，不引用任何外部资源（命名空间 URI 用 XML 字符引用书写，文件文本里不出现
外部 URL），同一输入 + 同一 ``generated_at`` 必得逐字节一致的字符串。

CLI::

    python mcp-server/tools/timeline.py --history <dir> [--out <svg>] [--title ...]
                                        [--json] [--check]

``--check`` 只校验 index，输出 ``{ok, steps, errors}``；默认写
``<history>/timeline.svg`` 并在 stdout 打一行 JSON 摘要；``--json`` 输出完整 payload。
退出码：``ok=0``，否则 ``1``。

演示（仓库内已有 5 步历史与图片，可重跑）::

    cd sysml-modeling-agent
    .venv/bin/python examples/timeline-demo/build_demo.py

只用 CLI 重画同一份历史（生成时间取当前时间；要逐字节复现示例，用上面的脚本，
它把 ``generated_at`` 固定为 ``2026-10-19T13:00:00.000Z``）::

    .venv/bin/python mcp-server/tools/timeline.py \
        --history examples/timeline-demo \
        --out examples/timeline-demo/timeline.svg

纯标准库；只读历史目录里的 index 与快照，不修改历史目录，也不修改传入的
``history`` / ``snapshots``。
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # 包内导入：``from tools.timeline import build_timeline``
    from .validator import KINDS
except ImportError:  # 直接当脚本运行：``python mcp-server/tools/timeline.py ...``
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.validator import KINDS

#: 本工具产出的时间线 / SVG 数据契约
TIMELINE_SCHEMA = "sysml-timeline/v1"

#: DSH 插件写出的历史目录 schema
HISTORY_SCHEMA = "sysml-viz-history/v1"

#: 快照 IR 的 schema（仅文档/兼容用；不满足也按 elements 是否合法降级）
IR_SCHEMA = "sysml-ir/v1"

#: 12 色步骤调色板（第 1 步从第一色开始，基线固定灰）
PALETTE: Tuple[str, ...] = (
    "#3b82f6",
    "#f59e0b",
    "#10b981",
    "#ef4444",
    "#a855f7",
    "#06b6d4",
    "#84cc16",
    "#ec4899",
    "#6366f1",
    "#14b8a6",
    "#f97316",
    "#8b5cf6",
)

#: 基线步 / 基线元素的固定颜色
BASELINE_COLOR = "#94a3b8"

#: 根节点（包名）的灰色
ROOT_COLOR = "#64748b"

#: 树边颜色
EDGE_COLOR = "#94a3b8"

#: 页面统一字体（系统字体，不依赖外部资源）
FONT_STACK = "-apple-system, 'PingFang SC', 'Noto Sans SC', sans-serif"

#: 节点排序 / 图例共用的 kind 顺序（合成 State 等未知 kind 置末）
KIND_ORDER: Tuple[str, ...] = tuple(KINDS)

_KIND_RANK: Dict[str, int] = {kind: index for index, kind in enumerate(KIND_ORDER)}

# 版面常量（全部整数，便于确定性输出）
_HEADER_H = 92
_PAGE_PAD = 28
_CARD_TOP = 114
_CARD_TITLE_DY = 26
_BODY_TOP_DY = 56
_LEGEND_W = 330
_GAP = 24
_NODE_H = 36
_LEVEL_GAP = 74
_SIB_GAP = 26
_MIN_NODE_W = 132
_MAX_NODE_W = 300
_TREE_CARD_PAD = 24
_CHART_H = 132
_CHART_BOTTOM_PAD = 24

#: SVG 命名空间。用 XML 字符引用写冒号，既保持命名空间语义正确，又让文件文本里
#: 不出现外部 URL 文本（避免被当成外部引用）。
_SVG_NS_ATTR = 'xmlns="http&#58;//www.w3.org/2000/svg"'

__all__ = [
    "TIMELINE_SCHEMA",
    "HISTORY_SCHEMA",
    "IR_SCHEMA",
    "PALETTE",
    "BASELINE_COLOR",
    "ROOT_COLOR",
    "EDGE_COLOR",
    "FONT_STACK",
    "KIND_ORDER",
    "TimelineError",
    "load_history",
    "build_timeline",
    "render_svg",
    "export_timeline",
    "main",
]


class TimelineError(Exception):
    """带稳定错误码的时间线异常（供 MCP server / CLI 区分失败原因）。

    :param code: 稳定错误码，如 ``E-HISTORY-NOT-FOUND``。
    :param message: 面向人的中文说明。
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:  # pragma: no cover - 仅调试/CLI 展示
        return "%s: %s" % (self.code, self.message)


# --------------------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------------------


def _error(code: str, message: str) -> Dict[str, Any]:
    return {"code": code, "message": message}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _as_text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _as_count(value: Any) -> Optional[int]:
    if _is_int(value) and value >= 0:
        return value
    return None


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _kind_rank(kind: Any) -> int:
    return _KIND_RANK.get(kind, len(KIND_ORDER))


def _sort_key(element: Dict[str, Any]) -> Tuple[int, str]:
    return (_kind_rank(element.get("kind")), str(element.get("id") or ""))


def _normalise_step(raw: Any, seq: int) -> Dict[str, Any]:
    """把 index 里的一条 step 归一化**为新 dict**（不修改入参）。"""
    result: Dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    result["seq"] = seq
    result["at"] = _as_text(result.get("at"))
    revision = result.get("revision")
    result["revision"] = revision if isinstance(revision, str) else ("" if revision is None else str(revision))
    result["sessionId"] = _as_text(result.get("sessionId"))
    result["elements"] = _as_count(result.get("elements"))
    result["relations"] = _as_count(result.get("relations"))
    result["added"] = _string_list(result.get("added"))
    result["removed"] = _string_list(result.get("removed"))
    result["changed"] = _string_list(result.get("changed"))
    source = _as_text(result.get("source"))
    result["source"] = source or ("baseline" if seq == 0 else "change")
    result["snapshot"] = _as_text(result.get("snapshot"))
    return result


def _snapshot_index(snapshots: Any) -> Dict[int, Dict[str, Any]]:
    """只保留「顶层 dict + elements 为 list」的可用快照，键统一为 int seq。"""
    result: Dict[int, Dict[str, Any]] = {}
    if not isinstance(snapshots, dict):
        return result
    for key, value in snapshots.items():
        try:
            seq = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and isinstance(value.get("elements"), list):
            result[seq] = value
    return result


def _ir_elements(ir: Any) -> List[Dict[str, Any]]:
    """从 IR 取元素记录（新 dict 列表），保留 relations 供计数。"""
    if not isinstance(ir, dict):
        return []
    raw = ir.get("elements")
    if not isinstance(raw, list):
        return []
    seen = set()
    result: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        element_id = item.get("id")
        if not isinstance(element_id, str) or not element_id or element_id in seen:
            continue
        seen.add(element_id)
        name = item.get("name")
        kind = item.get("kind")
        owner = item.get("owner")
        relations = item.get("relations")
        result.append(
            {
                "id": element_id,
                "name": name if isinstance(name, str) and name else element_id,
                "kind": kind if isinstance(kind, str) and kind else "Unknown",
                "owner": owner if isinstance(owner, str) and owner else None,
                "relations": [rel for rel in relations if isinstance(rel, dict)]
                if isinstance(relations, list)
                else [],
            }
        )
    return result


def _ir_package(ir: Any) -> str:
    if isinstance(ir, dict):
        package = ir.get("package")
        if isinstance(package, str) and package:
            return package
    return "Model"


def _snapshot_element_count(ir: Any) -> int:
    return len(_ir_elements(ir))


def _snapshot_relation_count(ir: Any) -> int:
    return sum(len(element["relations"]) for element in _ir_elements(ir))


# --------------------------------------------------------------------------------------
# 颜色
# --------------------------------------------------------------------------------------


def _hex_to_rgb(color: str) -> Tuple[int, int, int]:
    text = color.lstrip("#")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def _rgb_to_hsl(red: int, green: int, blue: int) -> Tuple[float, float, float]:
    r, g, b = red / 255.0, green / 255.0, blue / 255.0
    high, low = max(r, g, b), min(r, g, b)
    lightness = (high + low) / 2.0
    if high == low:
        return (0.0, 0.0, lightness)
    delta = high - low
    saturation = delta / (2.0 - high - low) if lightness > 0.5 else delta / (high + low)
    if high == r:
        hue = ((g - b) / delta) % 6.0
    elif high == g:
        hue = (b - r) / delta + 2.0
    else:
        hue = (r - g) / delta + 4.0
    return (hue * 60.0, saturation, lightness)


def _hue_to_rgb(p: float, q: float, t: float) -> float:
    if t < 0.0:
        t += 1.0
    if t > 1.0:
        t -= 1.0
    if t < 1.0 / 6.0:
        return p + (q - p) * 6.0 * t
    if t < 0.5:
        return q
    if t < 2.0 / 3.0:
        return p + (q - p) * (2.0 / 3.0 - t) * 6.0
    return p


def _hsl_to_hex(hue: float, saturation: float, lightness: float) -> str:
    saturation = min(1.0, max(0.0, saturation))
    lightness = min(1.0, max(0.0, lightness))
    if saturation == 0.0:
        red = green = blue = lightness
    else:
        q = lightness * (1.0 + saturation) if lightness < 0.5 else lightness + saturation - lightness * saturation
        p = 2.0 * lightness - q
        h = (hue % 360.0) / 360.0
        red = _hue_to_rgb(p, q, h + 1.0 / 3.0)
        green = _hue_to_rgb(p, q, h)
        blue = _hue_to_rgb(p, q, h - 1.0 / 3.0)
    return "#%02x%02x%02x" % (
        int(round(red * 255)),
        int(round(green * 255)),
        int(round(blue * 255)),
    )


def _palette_color(seq: int) -> str:
    """第 ``seq`` 步的颜色：1..12 直接用调色板；之后用 HSL 亮度分档区分。"""
    if seq <= 0:
        return BASELINE_COLOR
    index = seq - 1
    base = PALETTE[index % len(PALETTE)]
    cycle = index // len(PALETTE)
    if cycle == 0:
        return base
    hue, saturation, lightness = _rgb_to_hsl(*_hex_to_rgb(base))
    delta = 7.0 * ((cycle + 1) // 2) / 100.0
    lightness = lightness - delta if cycle % 2 == 1 else lightness + delta
    lightness = min(0.80, max(0.26, lightness))
    return _hsl_to_hex(hue, saturation, lightness)


def _step_color(step: Dict[str, Any]) -> str:
    if step.get("source") == "baseline" or step.get("seq") == 0:
        return BASELINE_COLOR
    return _palette_color(int(step.get("seq") or 0))


# --------------------------------------------------------------------------------------
# load_history
# --------------------------------------------------------------------------------------


def load_history(history_dir: Any) -> Dict[str, Any]:
    """读取并基本校验历史目录里的 ``index.json``。

    只校验：schema、steps 是数组、seq 从 0 连续；**不强制快照文件存在**（缺失/损坏在
    ``export_timeline`` 里降级成 warning）。失败抛 :class:`TimelineError`。

    :param history_dir: 历史目录（``.sysml-viz/history``）。
    :return: index 的浅拷贝；``steps`` 里每条都补齐默认字段。
    """
    try:
        path = Path(history_dir).expanduser()
    except (TypeError, ValueError):
        raise TimelineError("E-HISTORY-NOT-FOUND", "历史目录参数不是有效路径：%r。" % (history_dir,))
    if not path.exists() or not path.is_dir():
        raise TimelineError("E-HISTORY-NOT-FOUND", "历史目录不存在：`%s`。" % path)
    index_path = path / "index.json"
    if not index_path.is_file():
        raise TimelineError("E-HISTORY-NOT-FOUND", "历史目录里没有 index.json：`%s`。" % index_path)

    try:
        text = index_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise TimelineError("E-HISTORY-NOT-FOUND", "index.json 在读取前消失：`%s`。" % index_path)
    except UnicodeDecodeError as exc:
        raise TimelineError("E-HISTORY-SCHEMA", "index.json 不是 UTF-8 文本：`%s`（%s）。" % (index_path, exc))
    except OSError as exc:
        raise TimelineError("E-HISTORY-SCHEMA", "读取 index.json 失败：`%s`（%s）。" % (index_path, exc))

    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise TimelineError("E-HISTORY-SCHEMA", "index.json 不是合法 JSON：`%s`（%s）。" % (index_path, exc))
    if not isinstance(raw, dict):
        raise TimelineError(
            "E-HISTORY-SCHEMA",
            "index.json 顶层必须是 JSON 对象，实际是 %s。" % type(raw).__name__,
        )
    if raw.get("schema") != HISTORY_SCHEMA:
        raise TimelineError(
            "E-HISTORY-SCHEMA",
            "index.json schema 必须是 `%s`，实际是 %r。" % (HISTORY_SCHEMA, raw.get("schema")),
        )
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list):
        raise TimelineError("E-HISTORY-SCHEMA", "index.json 的 steps 必须是数组。")
    if not raw_steps:
        raise TimelineError("E-NO-STEPS", "index.json 的 steps 为空，没有可画的建模步骤。")

    steps: List[Dict[str, Any]] = []
    for position, item in enumerate(raw_steps):
        if not isinstance(item, dict):
            raise TimelineError("E-HISTORY-SCHEMA", "steps[%d] 必须是对象。" % position)
        seq = item.get("seq")
        if not _is_int(seq):
            raise TimelineError("E-HISTORY-SCHEMA", "steps[%d].seq 必须是整数。" % position)
        if seq != position:
            raise TimelineError(
                "E-HISTORY-SCHEMA",
                "steps 的 seq 必须从 0 开始连续：steps[%d].seq=%d。" % (position, seq),
            )
        steps.append(_normalise_step(item, seq))

    result = dict(raw)
    result["steps"] = steps
    return result


# --------------------------------------------------------------------------------------
# build_timeline
# --------------------------------------------------------------------------------------


def _cycle_nodes(parent: Dict[str, Optional[str]], order: List[str]) -> set:
    """在「每个节点至多一个父节点」的函数图上找出所有成环节点。"""
    state: Dict[str, int] = {element_id: 0 for element_id in order}
    cycles = set()
    for start in order:
        if state.get(start, 0) != 0:
            continue
        path: List[str] = []
        node: Optional[str] = start
        while node is not None:
            if state.get(node, 0) == 2:
                break
            if state.get(node, 0) == 1:
                # node 一定在当前 path 上（函数图 DFS）
                index = path.index(node)
                cycles.update(path[index:])
                break
            state[node] = 1
            path.append(node)
            node = parent.get(node)
        for visited in path:
            state[visited] = 2
    return cycles


def _build_tree(package: str, elements: List[Dict[str, Any]]) -> Dict[str, Any]:
    """按最终模型的 owner 关系构树；环 / 孤儿 / owner=包名都挂到根。"""
    by_id = {element["id"]: element for element in elements}
    ordered = sorted(elements, key=_sort_key)
    parent: Dict[str, Optional[str]] = {}
    for element in ordered:
        element_id = element["id"]
        owner = element.get("owner")
        if not owner or owner == package or owner == element_id or owner not in by_id:
            parent[element_id] = None
        else:
            parent[element_id] = owner

    cycles = _cycle_nodes(parent, [element["id"] for element in ordered])
    for element_id in sorted(cycles):
        parent[element_id] = None

    children: Dict[str, List[str]] = {}
    for element in ordered:
        element_id = element["id"]
        effective = parent.get(element_id)
        if effective is None:
            continue
        children.setdefault(effective, []).append(element_id)

    def make_node(element_id: str) -> Dict[str, Any]:
        element = by_id[element_id]
        node = {
            "id": element_id,
            "name": element.get("name") or element_id,
            "kind": element.get("kind") or "Unknown",
            "owner": element.get("owner"),
            "parent": parent.get(element_id) or package,
            "firstSeq": element["firstSeq"],
            "lastSeq": element["lastSeq"],
            "changedSeqs": list(element["changedSeqs"]),
            "color": element["color"],
            "children": [make_node(child) for child in children.get(element_id, [])],
        }
        return node

    root_children = [element["id"] for element in ordered if parent.get(element["id"]) is None]
    return {
        "id": package,
        "name": package,
        "kind": "Package",
        "owner": None,
        "parent": None,
        "firstSeq": 0,
        "lastSeq": 0,
        "changedSeqs": [],
        "color": ROOT_COLOR,
        "children": [make_node(element_id) for element_id in root_children],
    }


def build_timeline(history: Any, snapshots: Any) -> Dict[str, Any]:
    """把历史 index + ``{seq: IR}`` 合成内部时间线数据（纯函数、确定性）。

    最终树元素取自**最后一个成功加载的快照**；某步快照缺失时，该步沿用上一步可用的
    快照（第 0 步之前没有上一步时，才使用之后第一个可用快照）。缺失/坏快照的告警由
    ``export_timeline`` 负责收集，本函数只做容错跳过。index 里可选的 ``turn`` / ``note``
    （真实会话日志重建会写）会原样放进 steps 记录；其余必需字段形状不变。

    :param history: ``load_history`` 的返回值（或同形状 dict）。
    :param snapshots: ``{seq: IR dict}``；无效项会被忽略。
    :return: ``{steps, elements, tree, firstSeen, summary, colors}``。
    """
    raw_steps = history.get("steps") if isinstance(history, dict) else None
    steps: List[Dict[str, Any]] = []
    if isinstance(raw_steps, list):
        for position, item in enumerate(raw_steps):
            if not isinstance(item, dict):
                continue
            seq = item.get("seq")
            if not _is_int(seq):
                seq = position
            steps.append(_normalise_step(item, seq))
    steps.sort(key=lambda step: step["seq"])

    usable = _snapshot_index(snapshots)
    available = sorted(usable)
    resolved: Dict[int, Optional[Dict[str, Any]]] = {}
    pointer = -1
    for step in steps:
        seq = step["seq"]
        while pointer + 1 < len(available) and available[pointer + 1] <= seq:
            pointer += 1
        if pointer >= 0:
            resolved[seq] = usable[available[pointer]]
        elif available:
            resolved[seq] = usable[available[0]]  # 第 0 步快照缺失：用之后第一个可用快照
        else:
            resolved[seq] = None

    final_ir = resolved.get(steps[-1]["seq"]) if steps else None
    final_records = _ir_elements(final_ir)
    final_by_id = {record["id"]: record for record in final_records}
    package = _ir_package(final_ir)

    # ---- 基线 id：优先第 0 步快照；该快照缺失时用最早可用快照减去已记录的 added。
    baseline_ids = set()
    if steps and steps[0]["seq"] == 0 and 0 in usable:
        baseline_ids.update(record["id"] for record in _ir_elements(usable[0]))
    elif available:
        earliest = available[0]
        added_before = set()
        for step in steps:
            if 0 < step["seq"] <= earliest:
                added_before.update(step["added"])
        baseline_ids.update(
            record["id"] for record in _ir_elements(usable[earliest]) if record["id"] not in added_before
        )

    # ---- firstSeen：基线 0，其余按 index.added；元数据缺口再用快照顺序兜底。
    first_seen: Dict[str, int] = {}
    for element_id in sorted(baseline_ids):
        first_seen[element_id] = 0
    for step in steps:
        if step["seq"] == 0:
            continue
        for element_id in step["added"]:
            if element_id in final_by_id and element_id not in first_seen:
                first_seen[element_id] = step["seq"]
    snapshot_ids: Dict[int, set] = {
        seq: {record["id"] for record in _ir_elements(usable[seq])} for seq in available
    }
    for element_id in final_by_id:
        if element_id in first_seen:
            continue
        found = None
        for seq in available:
            if element_id in snapshot_ids[seq]:
                found = seq
                break
        first_seen[element_id] = 0 if found is None else found

    # ---- 修改步：只关心最终仍在的元素。
    changed_by_id: Dict[str, List[int]] = {element_id: [] for element_id in final_by_id}
    for step in steps:
        for element_id in step["changed"]:
            if element_id in changed_by_id and step["seq"] not in changed_by_id[element_id]:
                changed_by_id[element_id].append(step["seq"])

    # ---- 每步颜色：基线固定灰，其余按调色板 / HSL 分档。
    colors_by_seq: Dict[int, str] = {}
    for step in steps:
        colors_by_seq[step["seq"]] = _step_color(step)

    step_records: List[Dict[str, Any]] = []
    for step in steps:
        seq = step["seq"]
        is_baseline = step["source"] == "baseline" or seq == 0
        if seq == 0:
            label = "基线"
        elif is_baseline:
            label = "第 %d 步 · 基线" % seq
        else:
            label = "第 %d 步" % seq
        turn = step.get("turn")
        if _is_int(turn) and int(turn) > 0 and not is_baseline:
            # 有对话轮次信息时优先显示轮次（回答"第几轮各加了什么"）
            label = "第 %d 轮" % int(turn)
        element_count = step["elements"]
        if element_count is None:
            element_count = _snapshot_element_count(resolved.get(seq))
        relation_count = step["relations"]
        if relation_count is None:
            relation_count = _snapshot_relation_count(resolved.get(seq))
        step_records.append(
            {
                "seq": seq,
                "at": step["at"],
                "revision": step["revision"],
                "sessionId": step["sessionId"],
                "elements": element_count,
                "relations": relation_count,
                "added": list(step["added"]),
                "removed": list(step["removed"]),
                "changed": list(step["changed"]),
                "source": step["source"],
                "color": colors_by_seq[seq],
                "label": label,
                "turn": int(step["turn"]) if _is_int(step.get("turn")) and int(step.get("turn")) > 0 else None,
                "note": _as_text(step.get("note")),
            }
        )

    element_records: List[Dict[str, Any]] = []
    for record in sorted(final_records, key=_sort_key):
        element_id = record["id"]
        first_seq = first_seen.get(element_id, 0)
        changed_seqs = changed_by_id.get(element_id, [])
        element_records.append(
            {
                "id": element_id,
                "name": record["name"],
                "kind": record["kind"],
                "owner": record["owner"],
                "firstSeq": first_seq,
                "lastSeq": changed_seqs[-1] if changed_seqs else first_seq,
                "changedSeqs": list(changed_seqs),
                "color": colors_by_seq.get(first_seq, _palette_color(first_seq)),
            }
        )

    tree = _build_tree(package, element_records)
    relation_total = sum(len(record["relations"]) for record in final_records)
    summary = {
        "steps": len(step_records),
        "elements": len(element_records),
        "relations": relation_total,
        "firstAt": step_records[0]["at"] if step_records else None,
        "lastAt": step_records[-1]["at"] if step_records else None,
        "addedByStep": [
            {"seq": step["seq"], "count": len(step["added"]), "ids": list(step["added"])}
            for step in step_records
        ],
        "changedCount": sum(len(step["changed"]) for step in step_records),
        "removedCount": sum(len(step["removed"]) for step in step_records),
    }
    return {
        "steps": step_records,
        "elements": element_records,
        "tree": tree,
        "firstSeen": {element["id"]: element["firstSeq"] for element in element_records},
        "summary": summary,
        "colors": [step["color"] for step in step_records],
    }


# --------------------------------------------------------------------------------------
# SVG 文本工具
# --------------------------------------------------------------------------------------


def _esc(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _num(value: float) -> str:
    rounded = round(float(value), 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    text = ("%.2f" % rounded).rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _text_width(text: Any, size: float, bold: bool = False) -> float:
    total = 0.0
    for char in str(text):
        if unicodedata.east_asian_width(char) in ("W", "F"):
            total += size
        elif char == " ":
            total += size * 0.30
        else:
            total += size * 0.56
    if bold:
        total *= 1.03
    return total


def _truncate(text: Any, max_width: float, size: float, bold: bool = False) -> str:
    value = str(text)
    if max_width <= 0:
        return ""
    if _text_width(value, size, bold) <= max_width:
        return value
    ellipsis = "…"
    ellipsis_width = _text_width(ellipsis, size, bold)
    if ellipsis_width > max_width:
        return ""
    kept: List[str] = []
    width = 0.0
    for char in value:
        char_width = _text_width(char, size, bold)
        if width + char_width + ellipsis_width > max_width:
            break
        kept.append(char)
        width += char_width
    return "".join(kept).rstrip() + ellipsis


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _local_time(value: Any, fmt: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return "—"
    parsed = _parse_iso(value)
    if parsed is None:
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime(fmt)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _int_option(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------------------
# SVG 布局
# --------------------------------------------------------------------------------------


def _node_label(node: Dict[str, Any]) -> str:
    return str(node.get("name") or node.get("id") or "?")


def _last_changed(node: Dict[str, Any]) -> Optional[int]:
    changed = node.get("changedSeqs")
    if isinstance(changed, list) and changed:
        numerics = [value for value in changed if _is_int(value)]
        if numerics:
            return max(numerics)
    last_seq = node.get("lastSeq")
    first_seq = node.get("firstSeq")
    if _is_int(last_seq) and _is_int(first_seq) and last_seq > first_seq:
        return last_seq
    return None


def _measure_node(node: Dict[str, Any], is_root: bool) -> int:
    label = _node_label(node)
    if is_root:
        width = _text_width(label, 13, True) + 14 + 30
        return max(160, min(_MAX_NODE_W, int(round(width))))
    right_pad = 64 if _last_changed(node) is not None else 40
    width = _text_width(label, 12, True) + 12 + right_pad
    return max(_MIN_NODE_W, min(_MAX_NODE_W, int(round(width))))


def _layout_node(node: Dict[str, Any], is_root: bool) -> Dict[str, Any]:
    child_nodes = [child for child in node.get("children") or [] if isinstance(child, dict)]
    child_nodes.sort(key=_sort_key)
    child_layouts = [_layout_node(child, False) for child in child_nodes]
    node_width = _measure_node(node, is_root)
    if not child_layouts:
        width = float(node_width)
        center = width / 2.0
        placed: List[Tuple[float, Dict[str, Any]]] = []
    else:
        span = sum(child["width"] for child in child_layouts) + _SIB_GAP * (len(child_layouts) - 1)
        width = float(max(node_width, span))
        offset = (width - span) / 2.0
        placed = []
        for child in child_layouts:
            placed.append((offset, child))
            offset += child["width"] + _SIB_GAP
        center = width / 2.0
    return {
        "node": node,
        "is_root": is_root,
        "node_width": node_width,
        "width": width,
        "center": center,
        "children": placed,
    }


def _assign_positions(layout: Dict[str, Any], origin: float, top: float, depth: int) -> List[Dict[str, Any]]:
    x = origin + layout["center"] - layout["node_width"] / 2.0
    y = top + depth * _LEVEL_GAP
    position = {
        "layout": layout,
        "node": layout["node"],
        "x": x,
        "y": y,
        "width": layout["node_width"],
        "depth": depth,
        "children": [],
    }
    for offset, child in layout["children"]:
        child_position = _assign_positions(child, origin + offset, top, depth + 1)
        position["children"].append(child_position)
    return position


def _flatten_positions(position: Dict[str, Any]) -> List[Dict[str, Any]]:
    flat = [position]
    for child in position["children"]:
        flat.extend(_flatten_positions(child))
    return flat


def _max_depth(position: Dict[str, Any]) -> int:
    depth = position["depth"]
    for child in position["children"]:
        depth = max(depth, _max_depth(child))
    return depth


# --------------------------------------------------------------------------------------
# render_svg
# --------------------------------------------------------------------------------------


def _legend_names(added: List[str], name_by_id: Dict[str, str], max_width: float) -> str:
    names = [name_by_id.get(element_id, element_id) for element_id in added[:4]]
    if len(added) > 4:
        suffix = " 等 %d 个" % len(added)
        suffix_width = _text_width(suffix, 10, False)
        body = _truncate("、".join(names), max_width - suffix_width, 10, False)
        if not body:
            return suffix.strip()
        return body + suffix
    return _truncate("、".join(names), max_width, 10, False)


def _warning_summary(warnings: List[Dict[str, Any]]) -> Optional[str]:
    missing = sum(1 for warning in warnings if warning.get("code") == "W-SNAPSHOT-MISSING")
    broken = sum(1 for warning in warnings if warning.get("code") == "W-SNAPSHOT-PARSE")
    other = len(warnings) - missing - broken
    parts = []
    if missing:
        parts.append("%d 个快照缺失" % missing)
    if broken:
        parts.append("%d 个快照损坏" % broken)
    if other:
        parts.append("%d 条降级提示" % other)
    if not parts:
        return None
    return "⚠ " + "、".join(parts) + "，已用相邻快照降级"


def render_svg(timeline: Dict[str, Any], opts: Optional[Dict[str, Any]] = None) -> str:
    """把 ``build_timeline`` 的结果画成确定性 SVG 字符串。

    :param timeline: ``build_timeline`` 的返回值；额外容忍 ``warnings`` 键（仅用于页眉注记）。
    :param opts: ``{title, subtitle, generated_at, width}``；``generated_at`` 固定时，
        同一输入必得逐字节一致的 SVG。
    :return: 以 ``<?xml`` 开头的 SVG 文本。
    """
    options = dict(opts or {})
    steps = [step for step in timeline.get("steps") or [] if isinstance(step, dict)]
    elements = [element for element in timeline.get("elements") or [] if isinstance(element, dict)]
    summary = timeline.get("summary") if isinstance(timeline.get("summary"), dict) else {}
    tree = timeline.get("tree") if isinstance(timeline.get("tree"), dict) else None

    name_by_id = {
        str(element.get("id")): str(element.get("name") or element.get("id"))
        for element in elements
        if isinstance(element.get("id"), str)
    }
    colors_by_seq: Dict[int, str] = {}
    for step in steps:
        if _is_int(step.get("seq")):
            colors_by_seq[int(step["seq"])] = str(step.get("color") or _step_color(step))

    if tree is not None:
        root_layout = _layout_node(tree, True)
        tree_width = int(round(root_layout["width"]))
        tree_height = _max_depth(_assign_positions(root_layout, 0.0, 0.0, 0)) * _LEVEL_GAP + _NODE_H
    else:
        root_layout = None
        tree_width = 0
        tree_height = _NODE_H

    # 图例行高：有新增名字时多一行；图例可高于树。
    legend_rows: List[Dict[str, Any]] = []
    for step in steps:
        added = [item for item in step.get("added") or [] if isinstance(item, str)]
        names = _legend_names(added, name_by_id, _LEGEND_W - 60.0) if added else ""
        legend_rows.append({"step": step, "added": added, "names": names, "height": 58 if names else 44})
    legend_height = sum(row["height"] for row in legend_rows) if legend_rows else 44

    width_option = _int_option(options.get("width"))
    required_tree = (
        2 * _PAGE_PAD + tree_width + 2 * _TREE_CARD_PAD + _GAP + _LEGEND_W
    )
    required_chart = 2 * _PAGE_PAD + 40 + max(1, len(steps)) * 10
    width = max(1280, width_option or 0, required_tree, required_chart)
    left_width = width - 2 * _PAGE_PAD - _GAP - _LEGEND_W
    legend_x = _PAGE_PAD + left_width + _GAP

    card_top = _CARD_TOP
    body_top = card_top + _BODY_TOP_DY
    tree_bottom = body_top + tree_height
    legend_bottom = body_top + legend_height
    content_bottom = max(tree_bottom, legend_bottom, body_top + 40)
    card_bottom = content_bottom + 24
    card_height = card_bottom - card_top
    chart_top = card_bottom + 18
    height = chart_top + _CHART_H + _CHART_BOTTOM_PAD

    package = "Model"
    if tree is not None:
        package = str(tree.get("name") or tree.get("id") or "Model")
    title = options.get("title")
    if not isinstance(title, str) or not title:
        title = "建模全过程 · %s" % package
    subtitle = options.get("subtitle")
    if not isinstance(subtitle, str) or not subtitle:
        subtitle = "%d 步 · %d 元素 · %d 关系 · %s → %s" % (
            int(summary.get("steps") or len(steps)),
            int(summary.get("elements") or len(elements)),
            int(summary.get("relations") or 0),
            _local_time(summary.get("firstAt"), "%Y-%m-%d %H:%M:%S"),
            _local_time(summary.get("lastAt"), "%Y-%m-%d %H:%M:%S"),
        )
    generated_at = options.get("generated_at")
    if not generated_at:
        generated_at = summary.get("lastAt") or summary.get("firstAt")
    generated_text = _local_time(generated_at, "%Y-%m-%d %H:%M:%S")

    warnings = options.get("warnings")
    if warnings is None:
        warnings = timeline.get("warnings")
    warning_list = [warning for warning in warnings if isinstance(warning, dict)] if isinstance(warnings, list) else []
    warning_text = _warning_summary(warning_list)

    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        '<svg %s width="%d" height="%d" viewBox="0 0 %d %d" '
        'font-family="%s">'
        % (_SVG_NS_ATTR, width, height, width, height, _esc(FONT_STACK))
    )
    lines.append('<rect width="%d" height="%d" fill="#f8fafc"/>' % (width, height))
    lines.append('<rect width="%d" height="%d" fill="#ffffff"/>' % (width, _HEADER_H))
    lines.append(
        '<rect x="%d" y="22" width="4" height="30" rx="2" fill="#3b82f6"/>' % _PAGE_PAD
    )
    title_max = width - _PAGE_PAD * 2 - 360
    lines.append(
        '<text x="44" y="42" font-size="21" font-weight="700" fill="#0f172a">%s</text>'
        % _esc(_truncate(title, title_max, 21, True))
    )
    lines.append(
        '<text x="44" y="66" font-size="12" fill="#475569">%s</text>'
        % _esc(_truncate(subtitle, title_max, 12, False))
    )
    lines.append(
        '<text x="%d" y="30" text-anchor="end" font-size="10" fill="#94a3b8">生成时间 %s · %s</text>'
        % (width - _PAGE_PAD, _esc(generated_text), TIMELINE_SCHEMA)
    )
    if warning_text:
        lines.append(
            '<text x="%d" y="49" text-anchor="end" font-size="10" fill="#d97706">%s</text>'
            % (width - _PAGE_PAD, _esc(warning_text))
        )
    lines.append(
        '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#e2e8f0" stroke-width="1"/>'
        % (_PAGE_PAD, _HEADER_H, width - _PAGE_PAD, _HEADER_H)
    )

    # ---- 左卡片：最终系统生长树
    lines.append(
        '<rect x="%d" y="%d" width="%d" height="%d" rx="14" fill="#ffffff" stroke="#e2e8f0"/>'
        % (_PAGE_PAD, card_top, left_width, card_height)
    )
    lines.append(
        '<text x="%d" y="%d" font-size="13" font-weight="700" fill="#0f172a">系统生长树 · 最终模型</text>'
        % (_PAGE_PAD + 20, card_top + _CARD_TITLE_DY)
    )
    depth_label = "0 元素"
    if root_layout is not None:
        max_depth = _max_depth(_assign_positions(root_layout, 0.0, 0.0, 0))
        depth_label = "%d 元素 · %d 层" % (len(elements), max_depth + 1)
    note_x = min(_PAGE_PAD + left_width - 20, _PAGE_PAD + 900)
    lines.append(
        '<text x="%d" y="%d" text-anchor="end" font-size="10" fill="#94a3b8">%s</text>'
        % (note_x, card_top + _CARD_TITLE_DY, _esc(depth_label))
    )

    if root_layout is not None:
        tree_origin = _PAGE_PAD + max(
            float(_TREE_CARD_PAD), (left_width - tree_width) / 2.0
        )
        root_position = _assign_positions(root_layout, tree_origin, body_top, 0)
        positions = _flatten_positions(root_position)

        # 先画边，再画节点，保证节点压在折线之上。
        for position in positions:
            parent = position["node"]
            if position["depth"] == 0:
                continue
            parent_position = None
            for candidate in positions:
                if any(child is position for child in candidate["children"]):
                    parent_position = candidate
                    break
            if parent_position is None:
                continue
            px = parent_position["x"] + parent_position["width"] / 2.0
            py = parent_position["y"] + _NODE_H
            cx = position["x"] + position["width"] / 2.0
            cy = position["y"]
            mid_y = py + (_LEVEL_GAP - _NODE_H) / 2.0
            if abs(px - cx) < 0.01:
                path = "M %s %s V %s" % (_num(px), _num(py), _num(cy))
            else:
                path = "M %s %s V %s H %s V %s" % (
                    _num(px),
                    _num(py),
                    _num(mid_y),
                    _num(cx),
                    _num(cy),
                )
            lines.append(
                '<path d="%s" fill="none" stroke="%s" stroke-width="1.5" stroke-linecap="round"/>'
                % (path, EDGE_COLOR)
            )

        for position in positions:
            node = position["node"]
            is_root = position["depth"] == 0
            x = position["x"]
            y = position["y"]
            w = position["width"]
            label = _node_label(node)
            if is_root:
                fill = ROOT_COLOR
                text_pad_left = 14
                text_pad_right = 30
                label_text = _truncate(label, w - text_pad_left - text_pad_right, 13, True)
                lines.append('<g data-id="%s" data-kind="Package" data-first-seq="0">' % _esc(node.get("id")))
                lines.append('<title>%s · Package · 根</title>' % _esc(str(node.get("id") or label)))
                lines.append(
                    '<rect x="%s" y="%s" width="%s" height="%d" rx="9" fill="%s"/>'
                    % (_num(x), _num(y), _num(w), _NODE_H, fill)
                )
                lines.append(
                    '<text x="%s" y="%s" font-size="13" font-weight="700" fill="#ffffff">%s</text>'
                    % (_num(x + text_pad_left), _num(y + 23), _esc(label_text))
                )
                lines.append("</g>")
                continue

            first_seq = node.get("firstSeq")
            first_seq = int(first_seq) if _is_int(first_seq) else 0
            fill = str(node.get("color") or colors_by_seq.get(first_seq) or _palette_color(first_seq))
            changed_seq = _last_changed(node)
            changed_color = ""
            if changed_seq is not None:
                changed_color = colors_by_seq.get(changed_seq, _palette_color(changed_seq))
            right_pad = 64 if changed_seq is not None else 40
            label_text = _truncate(label, w - 12 - right_pad, 12, True)
            id_text = str(node.get("id") or "")
            kind_text = str(node.get("kind") or "Unknown")
            node_title = "%s · %s · %s" % (
                id_text,
                kind_text,
                "基线元素" if first_seq == 0 else "第%d步新增" % first_seq,
            )
            if changed_seq is not None:
                node_title += " · 第%d步修改" % changed_seq
            lines.append(
                '<g data-id="%s" data-kind="%s" data-first-seq="%d">'
                % (_esc(id_text), _esc(kind_text), first_seq)
            )
            lines.append("<title>%s</title>" % _esc(node_title))
            if changed_seq is not None:
                lines.append(
                    '<rect x="%s" y="%s" width="%s" height="%d" rx="9" fill="%s" '
                    'fill-opacity="0.92" stroke="%s" stroke-width="2"/>'
                    % (_num(x), _num(y), _num(w), _NODE_H, fill, changed_color)
                )
            else:
                lines.append(
                    '<rect x="%s" y="%s" width="%s" height="%d" rx="9" fill="%s" fill-opacity="0.92"/>'
                    % (_num(x), _num(y), _num(w), _NODE_H, fill)
                )
            lines.append(
                '<text x="%s" y="%s" font-size="12" font-weight="700" fill="#ffffff">%s</text>'
                % (_num(x + 12), _num(y + 23), _esc(label_text))
            )
            # 右上角步序号徽标（基线显示 0）
            badge_x = x + w - 11
            badge_y = y + 11
            lines.append(
                '<circle cx="%s" cy="%s" r="9" fill="#ffffff" fill-opacity="0.95"/>'
                % (_num(badge_x), _num(badge_y))
            )
            lines.append(
                '<text x="%s" y="%s" text-anchor="middle" font-size="8.5" font-weight="700" '
                'fill="#334155">%d</text>'
                % (_num(badge_x), _num(badge_y + 3), first_seq)
            )
            if changed_seq is not None:
                tag = "△%d" % changed_seq
                tag_width = max(28.0, _text_width(tag, 8.5, True) + 12.0)
                tag_x = x + w - 24 - tag_width
                tag_y = y + 2
                lines.append(
                    '<rect x="%s" y="%s" width="%s" height="15" rx="7" fill="%s"/>'
                    % (_num(tag_x), _num(tag_y), _num(tag_width), changed_color)
                )
                lines.append(
                    '<text x="%s" y="%s" text-anchor="middle" font-size="8.5" font-weight="700" '
                    'fill="#ffffff">%s</text>'
                    % (_num(tag_x + tag_width / 2.0), _num(tag_y + 11), _esc(tag))
                )
            lines.append("</g>")

    # ---- 右卡片：步骤图例
    lines.append(
        '<rect x="%d" y="%d" width="%d" height="%d" rx="14" fill="#ffffff" stroke="#e2e8f0"/>'
        % (legend_x, card_top, _LEGEND_W, card_height)
    )
    lines.append(
        '<text x="%d" y="%d" font-size="13" font-weight="700" fill="#0f172a">建模步骤</text>'
        % (legend_x + 18, card_top + _CARD_TITLE_DY)
    )
    lines.append(
        '<text x="%d" y="%d" text-anchor="end" font-size="10" fill="#94a3b8">%d 步</text>'
        % (legend_x + _LEGEND_W - 18, card_top + _CARD_TITLE_DY, len(steps))
    )

    row_top = body_top
    for index, row in enumerate(legend_rows):
        step = row["step"]
        seq = int(step.get("seq") or 0)
        color = str(step.get("color") or colors_by_seq.get(seq) or _palette_color(seq))
        is_baseline = step.get("source") == "baseline" or seq == 0
        if seq == 0:
            label = "第 0 步"
        else:
            label = str(step.get("label") or ("第 %d 步" % seq))
            if is_baseline and "基线" not in label:
                label += " · 基线"
        time_text = _local_time(step.get("at"), "%m-%d %H:%M:%S")
        added = row["added"]
        changed = [item for item in step.get("changed") or [] if isinstance(item, str)]
        removed = [item for item in step.get("removed") or [] if isinstance(item, str)]
        session = step.get("sessionId")
        session_text = "会话 %s" % str(session)[:8] if isinstance(session, str) and session else ""
        source = step.get("source")
        if source and source not in ("baseline", "change"):
            session_text = (session_text + " · " if session_text else "") + "日志重建"

        lines.append('<g data-seq="%d">' % seq)
        lines.append(
            '<rect x="%d" y="%d" width="16" height="16" rx="4" fill="%s"/>'
            % (legend_x + 18, row_top + 6, color)
        )
        lines.append(
            '<text x="%d" y="%d" font-size="12" font-weight="700" fill="#0f172a">%s</text>'
            % (legend_x + 42, row_top + 18, _esc(label))
        )
        lines.append(
            '<text x="%d" y="%d" text-anchor="end" font-size="10" fill="#64748b">%s</text>'
            % (legend_x + _LEGEND_W - 18, row_top + 18, _esc(time_text))
        )
        if session_text:
            lines.append(
                '<text x="%d" y="%d" font-size="9.5" fill="#94a3b8">%s</text>'
                % (legend_x + 42, row_top + 34, _esc(session_text))
            )
        if is_baseline:
            note = "基线 · 已有 %d 个元素" % int(step.get("elements") or 0)
            lines.append(
                '<text x="%d" y="%d" text-anchor="end" font-size="9.5" font-weight="600" '
                'fill="#64748b">%s</text>'
                % (legend_x + _LEGEND_W - 18, row_top + 34, _esc(note))
            )
        else:
            stats = []
            if added:
                stats.append(("+%d" % len(added), "#059669"))
            if changed:
                stats.append(("~%d" % len(changed), "#d97706"))
            if removed:
                stats.append(("-%d" % len(removed), "#dc2626"))
            if not stats:
                stats.append(("无变化", "#94a3b8"))
            tspans = " ".join(
                '<tspan fill="%s">%s</tspan>' % (stat_color, _esc(stat_text))
                for stat_text, stat_color in stats
            )
            lines.append(
                '<text x="%d" y="%d" text-anchor="end" font-size="9.5" font-weight="600">%s</text>'
                % (legend_x + _LEGEND_W - 18, row_top + 34, tspans)
            )
        if row["names"]:
            lines.append(
                '<text x="%d" y="%d" font-size="10" fill="#64748b">'
                '<tspan fill="#10b981" font-weight="700">＋</tspan> %s</text>'
                % (legend_x + 42, row_top + 50, _esc(row["names"]))
            )
        lines.append("</g>")
        if index != len(legend_rows) - 1:
            lines.append(
                '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#e2e8f0" stroke-width="1"/>'
                % (legend_x + 18, row_top + row["height"], legend_x + _LEGEND_W - 18, row_top + row["height"])
            )
        row_top += row["height"]

    # ---- 底部：元素数生长曲线 + 步骤色带
    lines.append(
        '<rect x="%d" y="%d" width="%d" height="%d" rx="14" fill="#ffffff" stroke="#e2e8f0"/>'
        % (_PAGE_PAD, chart_top, width - 2 * _PAGE_PAD, _CHART_H)
    )
    lines.append(
        '<text x="%d" y="%d" font-size="11" font-weight="700" fill="#475569">元素数 / 步</text>'
        % (_PAGE_PAD + 20, chart_top + 24)
    )
    base_y = chart_top + _CHART_H - 20
    plot_height = 74.0
    max_elements = max([int(step.get("elements") or 0) for step in steps] or [0])
    lines.append(
        '<line x1="%d" y1="%s" x2="%d" y2="%s" stroke="#cbd5e1" stroke-width="1"/>'
        % (_PAGE_PAD + 20, _num(base_y), width - _PAGE_PAD - 20, _num(base_y))
    )
    if steps:
        chart_inner = width - 2 * _PAGE_PAD - 40
        count = len(steps)
        slot_width = chart_inner / float(count)
        bar_width = max(8.0, min(40.0, slot_width))
        for index, step in enumerate(steps):
            seq = int(step.get("seq") or 0)
            total = int(step.get("elements") or 0)
            ratio = (float(total) / float(max_elements)) if max_elements else 0.0
            bar_height = plot_height * ratio
            if total > 0:
                bar_height = max(3.0, bar_height)
            center_x = _PAGE_PAD + 20 + slot_width * (index + 0.5)
            bar_x = center_x - bar_width / 2.0
            bar_y = base_y - bar_height
            color = str(step.get("color") or colors_by_seq.get(seq) or _palette_color(seq))
            lines.append(
                '<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" fill-opacity="0.92"/>'
                % (_num(bar_x), _num(bar_y), _num(bar_width), _num(bar_height), _num(min(3.0, bar_width / 2.0)), color)
            )
            if total > 0:
                lines.append(
                    '<text x="%s" y="%s" text-anchor="middle" font-size="8.5" fill="#475569">%d</text>'
                    % (_num(center_x), _num(bar_y - 4), total)
                )
            lines.append(
                '<text x="%s" y="%s" text-anchor="middle" font-size="8.5" fill="#94a3b8">%d</text>'
                % (_num(center_x), _num(base_y + 13), seq)
            )
    else:
        lines.append(
            '<text x="%d" y="%d" text-anchor="middle" font-size="11" fill="#94a3b8">无步骤</text>'
            % (width // 2, chart_top + 76)
        )

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# export_timeline
# --------------------------------------------------------------------------------------


def _failure_payload(
    errors: List[Dict[str, Any]], warnings: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    return {
        "ok": False,
        "schema": TIMELINE_SCHEMA,
        "svgPath": None,
        "summary": None,
        "steps": [],
        "errors": list(errors),
        "warnings": list(warnings or []),
    }


def _read_snapshots(
    history_dir: Path, history: Dict[str, Any]
) -> Tuple[Dict[int, Dict[str, Any]], List[Dict[str, Any]]]:
    snapshots: Dict[int, Dict[str, Any]] = {}
    warnings: List[Dict[str, Any]] = []
    for step in history.get("steps") or []:
        if not isinstance(step, dict):
            continue
        seq = step.get("seq")
        if not _is_int(seq):
            continue
        snapshot = step.get("snapshot")
        if not isinstance(snapshot, str) or not snapshot:
            warnings.append(
                _error("W-SNAPSHOT-MISSING", "第 %d 步没有 snapshot 文件名，已回退到相邻快照。" % seq)
            )
            continue
        snapshot_path = Path(snapshot)
        if not snapshot_path.is_absolute():
            snapshot_path = history_dir / snapshot_path
        try:
            text = snapshot_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            warnings.append(
                _error("W-SNAPSHOT-MISSING", "第 %d 步快照缺失：`%s`。" % (seq, snapshot_path))
            )
            continue
        except UnicodeDecodeError as exc:
            warnings.append(
                _error("W-SNAPSHOT-PARSE", "第 %d 步快照不是 UTF-8：`%s`（%s）。" % (seq, snapshot_path, exc))
            )
            continue
        except OSError as exc:
            warnings.append(
                _error("W-SNAPSHOT-PARSE", "第 %d 步快照读取失败：`%s`（%s）。" % (seq, snapshot_path, exc))
            )
            continue
        try:
            ir = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            warnings.append(
                _error(
                    "W-SNAPSHOT-PARSE",
                    "第 %d 步快照不是合法 JSON：`%s`（%s）。" % (seq, snapshot_path, exc),
                )
            )
            continue
        if not isinstance(ir, dict) or not isinstance(ir.get("elements"), list):
            warnings.append(
                _error("W-SNAPSHOT-PARSE", "第 %d 步快照缺少 elements 数组：`%s`。" % (seq, snapshot_path))
            )
            continue
        snapshots[seq] = ir
    return snapshots, warnings


def _export_timeline(
    history_dir: Any,
    out_path: Any,
    title: Optional[str],
    generated_at: Optional[str],
) -> Dict[str, Any]:
    history = load_history(history_dir)
    base_dir = Path(history_dir).expanduser()
    snapshots, warnings = _read_snapshots(base_dir, history)
    timeline = build_timeline(history, snapshots)

    render_timeline = dict(timeline)
    render_timeline["warnings"] = warnings
    generated = generated_at if isinstance(generated_at, str) and generated_at else _now_iso()
    svg = render_svg(
        render_timeline,
        {"title": title, "generated_at": generated},
    )

    if out_path is None:
        output = base_dir / "timeline.svg"
    else:
        try:
            output = Path(out_path).expanduser()
        except (TypeError, ValueError):
            return {
                "ok": False,
                "schema": TIMELINE_SCHEMA,
                "svgPath": None,
                "summary": timeline["summary"],
                "steps": timeline["steps"],
                "errors": [_error("E-WRITE", "输出路径无效：%r。" % (out_path,))],
                "warnings": warnings,
            }

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(svg)
    except OSError as exc:
        return {
            "ok": False,
            "schema": TIMELINE_SCHEMA,
            "svgPath": None,
            "summary": timeline["summary"],
            "steps": timeline["steps"],
            "errors": [_error("E-WRITE", "写出 SVG 失败：`%s`（%s）。" % (output, exc))],
            "warnings": warnings,
        }

    return {
        "ok": True,
        "schema": TIMELINE_SCHEMA,
        "svgPath": str(output),
        "summary": timeline["summary"],
        "steps": timeline["steps"],
        "errors": [],
        "warnings": warnings,
    }


def export_timeline(
    history_dir: Any,
    out_path: Any = None,
    *,
    title: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """读取历史目录并写出 ``timeline.svg``；**永不抛异常**。

    :param history_dir: 历史目录（含 ``index.json``）。
    :param out_path: 输出 SVG；省略时写 ``<history_dir>/timeline.svg``。
    :param title: 覆盖页眉标题（省略时用「建模全过程 · 包名」）。
    :param generated_at: 固定的生成时间（ISO 字符串）；省略时取当前 UTC 时间。
    :return: ``{ok, schema, svgPath, summary, steps, errors, warnings}``。
    """
    try:
        return _export_timeline(history_dir, out_path, title, generated_at)
    except TimelineError as exc:
        return _failure_payload([_error(exc.code, exc.message)])
    except Exception as exc:  # noqa: BLE001 - 输入来自外部文件，必须宽进严出
        return _failure_payload(
            [_error("E-INTERNAL", "时间线生成内部错误（已捕获）：%s: %s。" % (type(exc).__name__, exc))]
        )


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _check_history(history_dir: Any) -> Dict[str, Any]:
    try:
        history = load_history(history_dir)
        return {"ok": True, "steps": len(history["steps"]), "errors": []}
    except TimelineError as exc:
        return {"ok": False, "steps": 0, "errors": [_error(exc.code, exc.message)]}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "steps": 0,
            "errors": [_error("E-INTERNAL", "校验内部错误：%s: %s。" % (type(exc).__name__, exc))],
        }


def _print_payload(payload: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    line = {
        "ok": payload.get("ok"),
        "schema": payload.get("schema"),
        "steps": len(payload.get("steps") or []),
        "elements": summary.get("elements"),
        "relations": summary.get("relations"),
        "svgPath": payload.get("svgPath"),
    }
    if not payload.get("ok"):
        line["errors"] = payload.get("errors") or []
    sys.stdout.write(json.dumps(line, ensure_ascii=False) + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口；返回进程退出码（ok=0，错误=1）。"""
    parser = argparse.ArgumentParser(
        prog="timeline.py",
        description="模型修订历史 → sysml-timeline/v1 建模过程 SVG（纯标准库、确定性）。",
    )
    parser.add_argument("--history", required=True, help="历史目录（含 index.json）")
    parser.add_argument("--out", default=None, help="输出 SVG；省略时写 <history>/timeline.svg")
    parser.add_argument("--title", default=None, help="覆盖 SVG 标题")
    parser.add_argument("--json", action="store_true", dest="as_json", help="输出完整 payload JSON")
    parser.add_argument("--check", action="store_true", help="只校验 index，输出 {ok, steps, errors}")
    args = parser.parse_args(argv)

    if args.check:
        result = _check_history(args.history)
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        return 0 if result.get("ok") else 1

    payload = export_timeline(args.history, args.out, title=args.title)
    _print_payload(payload, bool(args.as_json))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
