#!/usr/bin/env python3
"""sysml-modeling-agent —— MCP 工具服务启动入口。

启动接口契约（《Win 电脑部署手册》与 README 按此引用，请勿随意改动）：

    python run_server.py [--transport stdio|streamable-http] [--port 8000]
                         [--auth-token <token>] [--host 127.0.0.1]

- ``--transport``   默认 ``stdio``；``streamable-http`` 用于云端（扣子/Coze）接入。
- ``--port``        默认 ``8000``；仅 ``streamable-http`` 生效。
- ``--auth-token``  可选；**仅 streamable-http 模式校验**，设置后要求请求头
                    ``Authorization: Bearer <token>``，不匹配返回 401。
- ``--host``        默认 ``127.0.0.1``（**仅本机回环**；内网穿透客户端与本体同机时够用，
                    见《Win 电脑部署手册》§3.6）。如需局域网/公网暴露，显式传
                    ``--host 0.0.0.0`` 并自担风险——默认不替你开全网卡监听。

依赖（见 requirements.txt）：
- 首选 ``fastmcp``，其次官方 ``mcp`` 的 ``mcp.server.fastmcp``；
- 三者都装不上时，本文件提供**等价的本地调用模式**（``--list-tools`` / ``--call``），
  核心逻辑仍是同一批纯函数，功能不减，只是没有 MCP 协议外壳。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# --------------------------------------------------------------------------------------
# 必须在导入 MCP 框架**之前**设置：关掉 fastmcp 的联网版本检查。
#
# 实测踩到的坑（macOS + 环境变量里配了 SOCKS 代理的机器）：fastmcp 启动时会去 PyPI 查新版本，
# 在只配了 `ALL_PROXY=socks5://...` 而没有装 `socksio` 的环境里会直接抛
# `ImportError: Using SOCKS proxy, but the 'socksio' package is not installed`，
# **服务器根本起不来**。我们的工具本身完全不依赖网络，没理由为了一次版本检查挂掉。
#
# 用 setdefault：想显式打开的人把它改成 `stable` 或 `prerelease` 即可
# （fastmcp 只接受 `stable` / `prerelease` / `off` 三个字面值，
#  写 `0` 会反而因 pydantic 校验失败而使 fastmcp 导入报错——这也是实测出来的）。
# --------------------------------------------------------------------------------------
os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from tools.export import export_simulink  # noqa: E402
from tools.generator import generate_sysml  # noqa: E402
from tools.official_parser import parse_with_official  # noqa: E402
from tools.parser import parse_sysml  # noqa: E402
from tools.patch import patch_model  # noqa: E402
from tools.query import query_model  # noqa: E402
from tools.sysml_lint import lint_sysml, roundtrip_check  # noqa: E402
from tools.timeline import export_timeline as export_timeline_svg  # noqa: E402
from tools.trace import traceability  # noqa: E402
from tools.validator import load_model, validate_model_json  # noqa: E402

SERVER_NAME = "sysml-modeling-agent"
SERVER_VERSION = "1.1.0"

INSTRUCTIONS = """\
SysML v2 建模智能体（二期）。核心路线是「LLM 填表、代码建模」：
你只产出/修改 IR JSON（结构化中间表示），确定性代码负责校验并渲染 SysML v2 文本。

固定顺序（不可打乱）：
1. query_model  先查现状——确认 id / 命名是否被占用、是否已有同类元素；
   （服务端本机也可用 path 代替 model，直接读本地 IR JSON 文件；path 的目录边界由
    环境变量 SYSML_QUERY_ROOT 控制，未设置时不限制）
   导入既有模型用 parse_sysml：先把 SysML v2 文本逆解析成 IR，再接到第 3 步校验；
   parse_sysml 只认本工具链的渲染子集（子集外构造会进 unsupported）。
2. 产出或修改 IR JSON（schema = sysml-ir/v1）；
3. validate_model_json  改到 errors 为空；
4. patch_model  可选：对已有模型做增/改/删（原子操作，失败整体回滚）；
   用了 patch_model 之后必须回到第 3 步重新 validate_model_json；
5. generate_sysml  渲染 SysML v2 文本；
6. verify_sysml  回验（lint + 元素级比对）；可选 official=true，在后端可用时
   额外调用官方 Pilot Implementation，结果放在返回的 official 键（不可用会如实标注）；
7. 可选：parse_sysml 做一次往返（文本 → IR），确认 IR 元素级等价、两次生成逐字节一致；
8. traceability  追溯检查——需求矩阵 / 缺口 / 影响面；
9. 可选：export_timeline  把 .sysml-viz/history/ 的建模步骤渲染成「建模全过程」SVG，
   用于回答"每一轮对话各加了什么"；不给 history_dir 时从 model_path / 当前工作目录往上找。

导出仿真参数表用 export_simulink（csv/json/md），不要手工抄参数。
出错时改 JSON，不要改文本——文本是代码生成的，手改会漂移。
"""

#: 工具契约（名称 / 描述 / 入参），也是 --list-tools 的输出
TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "validate_model_json",
        "description": (
            "以 Schema + 语义规则校验 IR JSON。检查必填字段、受控枚举、"
            "id 唯一、同 owner 下 name 唯一、owner 存在、relations.target 存在、"
            "PartUsage.typeRef 指向 PartDefinition、数值字段必须是数字等。"
            "返回 {ok, errors:[{code,element,message}], warnings:[...]}。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "object", "description": "IR JSON（schema=sysml-ir/v1）"},
                "use_json_schema": {
                    "type": ["boolean", "null"],
                    "description": "是否额外跑 JSON Schema 交叉检查层，默认自动。",
                },
            },
            "required": ["model"],
        },
    },
    {
        "name": "generate_sysml",
        "description": (
            "把 IR JSON 按模板确定性地渲染成 SysML v2 文本（同输入必得同输出）。"
            "渲染 part def/usage、requirement def、action def、state def、attribute，"
            "relations 渲染为追溯注释。IR 未通过校验时拒绝渲染并返回 errors。"
            "返回 {ok, text, errors, warnings, stats, sha256}。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "object", "description": "IR JSON（schema=sysml-ir/v1）"},
                "indent": {"type": "string", "description": "缩进单位，默认 4 个空格"},
                "include_header": {"type": "boolean", "description": "是否带生成器头注释"},
            },
            "required": ["model"],
        },
    },
    {
        "name": "query_model",
        "description": (
            "查模型现状：按关键字/kind 查元素、查某 id 的引用者、查重名、"
            "列未被满足的需求（无 satisfiedBy）。只读，不修改模型。"
            "输入二选一：model（IR JSON）或 path（服务端本地 IR JSON 文件路径）；"
            "两者同时给或都不给都会报错。"
            "引用边口径：relations[].target、properties.typeRef、"
            "Constraint.properties.parameters、Connection.properties.sourceRef/targetRef"
            "（owner 归属链不算引用边）。"
            "path 仅服务端本机可用；云端应上传内容而非路径。设置环境变量 SYSML_QUERY_ROOT 后，"
            "path（解析符号链接后）必须落在该根目录之下，否则报 E-QUERY-PATH-OUTSIDE-ROOT；"
            "变量本身不是合法目录则报 E-QUERY-PATH-ROOT-INVALID。"
            "streamable-http 启动时若未设置该变量，服务会默认把工作目录设为根并在启动输出里提示。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "object",
                    "description": "IR JSON（与 path 二选一）",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "服务端本地 IR JSON 文件路径（与 model 二选一）。"
                        "仅服务端本机可用；云端部署应上传内容而非路径。"
                    ),
                },
                "keyword": {"type": "string", "description": "关键字，大小写不敏感"},
                "query": {"type": "string", "description": "keyword 的别名"},
                "kind": {"type": "string", "description": "按 kind 过滤"},
                "referrers_of": {"type": "string", "description": "查谁引用了这个 id"},
                "duplicates": {"type": "boolean", "description": "查 id / name 重名"},
                "unsatisfied_requirements": {
                    "type": "boolean",
                    "description": "列未被满足的需求",
                },
                "details": {"type": "boolean", "description": "返回完整元素"},
                "limit": {"type": "integer", "description": "结果上限，默认 200"},
            },
        },
    },
    {
        "name": "verify_sysml",
        "description": (
            "回验生成的 SysML v2 文本：轻量语法自查（括号/注释/字符串/语句终结，均带"
            "行列定位）+ 声明抽取 + 与 IR 的元素级比对。可选 official=true 时额外调用"
            "官方 Pilot Implementation，结果放在 official 键（backend/status/diagnostics）；"
            "后端不可用时如实返回 status=unavailable，绝不当作通过。"
            "需要文本 → IR 的逆解析请用 parse_sysml。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "SysML v2 文本"},
                "model": {"type": "object", "description": "可选：给出 IR 则做元素级比对"},
                "official": {
                    "type": "boolean",
                    "description": "是否额外调用官方解析器（默认 false；无后端时如实降级）",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "patch_model",
        "description": (
            "对已有 IR JSON 做增量编辑（原子操作）：支持 add_element / update_element / "
            "remove_element / add_relation / remove_relation。任何一步非法、id 不存在或"
            "补丁后校验失败都会整体回滚，返回 errors 与说明回滚步骤的 diff，"
            "不返回半应用模型（ok=false 时 model 为 null）。"
            "返回 {ok, model, diff:[{change,kind,id,detail}], errors, warnings}。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "object", "description": "IR JSON（schema=sysml-ir/v1）"},
                "ops": {
                    "type": "array",
                    "description": (
                        "补丁步骤数组。add_element 用 {op,element}；update_element 用 "
                        "{op,id,element}（整体替换，element.id 必须等于 id）；remove_element 用 "
                        "{op,id,cascade?}；add_relation 用 {op,id,relation}；remove_relation 用 "
                        "{op,id,type,target}。"
                    ),
                    "items": {"type": "object"},
                },
                "validate": {
                    "type": "boolean",
                    "description": "补丁后是否重新校验，默认 true；false 仅供调试",
                },
            },
            "required": ["model", "ops"],
        },
    },
    {
        "name": "traceability",
        "description": (
            "生成需求追溯矩阵与覆盖缺口：每条 Requirement 的 satisfiedBy / verifiedBy / "
            "status（satisfied-and-verified / satisfied / verified-only / unsatisfied），"
            "并列出未满足需求、未被验证的需求、以及没有 verifies 关系的 ActionDefinition。"
            "可选 focus（id 或 id 列表）按引用关系做反向 BFS，给出直接/传递影响面与"
            "受影响需求；fmt=md 时额外返回渲染好的 Markdown 矩阵 content。"
            "返回 {ok, matrix, gaps, impact, content, errors}。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "object", "description": "IR JSON（schema=sysml-ir/v1）"},
                "focus": {
                    "description": "可选：元素 id 或 id 列表，给出时计算影响面",
                    "type": ["string", "array"],
                    "items": {"type": "string"},
                },
                "fmt": {
                    "type": "string",
                    "enum": ["json", "md"],
                    "description": "json（默认）或 md（额外返回 Markdown 矩阵 content）",
                },
            },
            "required": ["model"],
        },
    },
    {
        "name": "parse_sysml",
        "description": (
            "把 SysML v2 文本逆解析回 IR JSON（schema=sysml-ir/v1）。"
            "解析范围**仅限本工具链的渲染子集**（generate_sysml 的产物 + 同子集手写文本）："
            "八种 kind、[unit] / [n] 后缀、状态机、Constraint / Connection 结构化注释、"
            "// id: / // description: / 追溯关系注释。"
            "子集外构造（item/port/satisfy/裸 import/多行块注释等）不崩溃也不静默丢，"
            "逐条进 unsupported（带行号）并令 ok=false；名字→id 无法唯一还原时进 errors"
            "（E-PARSE-AMBIGUOUS / E-PARSE-UNRESOLVED），不猜测。"
            "返回 {ok, model, warnings, unsupported, errors, stats}；"
            "解析结果仍须过 validate_model_json。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "SysML v2 文本"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "export_simulink",
        "description": (
            "把 IR 里的参数与约束导出成仿真侧可消费的参数表 / 公式清单："
            "scope=attributes/constraints/requirements/all，fmt=csv（默认，UTF-8 BOM + "
            "固定表头）/json/md。参数值直接取自 IR，可能仍是占位值（非实测结论）。"
            "返回 {ok, content, rows, notes, errors}。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "object", "description": "IR JSON（schema=sysml-ir/v1）"},
                "fmt": {
                    "type": "string",
                    "enum": ["csv", "json", "md"],
                    "description": "输出格式，默认 csv",
                },
                "scope": {
                    "type": "string",
                    "enum": ["all", "attributes", "constraints", "requirements"],
                    "description": "导出范围，默认 all",
                },
            },
            "required": ["model"],
        },
    },
    {
        "name": "export_timeline",
        "description": (
            "把建模过程记录（<workspace>/.sysml-viz/history/ 的 index.json + 每步 IR 快照）"
            "渲染成「建模全过程」SVG：最终系统生长树按元素首次出现的步骤着色，右侧图例列出"
            "每步时间 / 会话短 id / 新增元素，底部是元素数曲线。history_dir 不传时从 model_path"
            "（若有）或当前工作目录向上查找 .sysml-viz/history。不修改 IR，只写 SVG。"
            "返回 {ok, schema:'sysml-timeline/v1', svgPath, summary, steps, errors, warnings}。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "history_dir": {
                    "type": "string",
                    "description": "历史目录（含 index.json 与 step-*.ir.json）；默认自动发现",
                },
                "model_path": {
                    "type": "string",
                    "description": "可选：当前 IR 文件路径，用于反推工作区的 .sysml-viz/history",
                },
                "output": {
                    "type": "string",
                    "description": "输出 SVG 路径；默认 <history_dir>/timeline.svg",
                },
                "title": {
                    "type": "string",
                    "description": "可选标题，默认「建模全过程 · <包名>」",
                },
            },
        },
    },
]

TOOL_NAMES = [spec["name"] for spec in TOOL_SPECS]

#: 按名字取工具契约（避免在注册处硬编码列表下标）
SPEC_BY_NAME = {spec["name"]: spec for spec in TOOL_SPECS}


# --------------------------------------------------------------------------------------
# 工具函数本体（与 MCP 框架无关，纯函数）
# --------------------------------------------------------------------------------------


def call_validate_model_json(model: Any, use_json_schema: Optional[bool] = None) -> Dict[str, Any]:
    return validate_model_json(model, use_json_schema=use_json_schema)


def call_generate_sysml(
    model: Any, indent: str = "    ", include_header: bool = True
) -> Dict[str, Any]:
    return generate_sysml(model, indent=indent, include_header=include_header)


def call_query_model(
    model: Any = None, *, path: Optional[str] = None, **kwargs: Any
) -> Dict[str, Any]:
    return query_model(model, path=path, **kwargs)


def call_verify_sysml(
    text: str, model: Any = None, official: bool = False
) -> Dict[str, Any]:
    """回验：lint（可带元素级比对）+ 可选的官方解析器结果。

    ``official=True`` 时把官方适配层的结果原样放进 ``official`` 键：

    - 只有 ``status="available"`` 且官方 ``ok is True`` 时，顶层 ``ok`` 才沿用内置回验结果；
    - 官方报错、``status="unavailable"``、``"unverified"`` 一律把顶层 ``ok`` 置 False
      （失败关闭：没拿到可信的官方结论，就不说通过），并在 ``official`` 里如实标注。
    """
    result = lint_sysml(text) if model is None else roundtrip_check(model, text)
    if not official:
        return result

    official_result = parse_with_official(text)
    enriched = dict(result)
    enriched["official"] = official_result
    # 失败关闭：显式要求官方校验时，只要没拿到「后端可用且 0 error」的结论，
    # 顶层就不返回 ok=True（unavailable / unverified / 有诊断都不算通过）。
    if official_result.get("status") != "available" or official_result.get("ok") is not True:
        enriched["ok"] = False
    return enriched


def call_parse_sysml(text: Any) -> Dict[str, Any]:
    return parse_sysml(text)


def call_export_simulink(
    model: Any, fmt: str = "csv", scope: str = "all"
) -> Dict[str, Any]:
    return export_simulink(model, fmt=fmt, scope=scope)


def call_patch_model(model: Any, ops: Any, validate: bool = True) -> Dict[str, Any]:
    return patch_model(model, ops, validate=validate)


def call_traceability(
    model: Any, focus: Any = None, fmt: str = "json"
) -> Dict[str, Any]:
    return traceability(model, focus=focus, fmt=fmt)


def _discover_history_dir(model_path: Optional[str] = None) -> Optional[str]:
    """从 env / model_path / cwd 向上找 ``.sysml-viz/history``（最多 7 层）。

    优先 ``SYSML_VIZ_HISTORY``（显式目录）；其次从 model 文件所在目录与当前工作目录
    逐级向上找含 ``index.json`` 的 ``.sysml-viz/history``。
    """
    explicit = os.environ.get("SYSML_VIZ_HISTORY")
    if explicit:
        return explicit
    starts: List[Path] = []
    if model_path:
        try:
            starts.append(Path(model_path).expanduser().resolve().parent)
        except (OSError, ValueError):
            pass
    try:
        starts.append(Path.cwd())
    except OSError:
        pass
    seen = set()
    for start in starts:
        current = start
        for _ in range(7):
            candidate = current / ".sysml-viz" / "history"
            key = str(candidate)
            if key not in seen:
                seen.add(key)
                if (candidate / "index.json").is_file():
                    return key
            parent = current.parent
            if parent == current:
                break
            current = parent
    return None


def call_export_timeline(
    history_dir: Optional[str] = None,
    model_path: Optional[str] = None,
    output: Optional[str] = None,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """把建模过程记录渲染成「建模全过程」SVG（``tools.timeline.export_timeline``）。

    没显式给 ``history_dir`` 时自动发现；找不到就让底层返回 ``E-HISTORY-NOT-FOUND``，
    并补一条说明，避免调用方误以为服务坏了。
    """
    resolved = history_dir or _discover_history_dir(model_path)
    fallback = str(Path.cwd() / ".sysml-viz" / "history")
    result = export_timeline_svg(resolved or fallback, out_path=output, title=title)
    if resolved is None and result.get("ok") is not True:
        errors = result.get("errors")
        if not isinstance(errors, list):
            errors = []
        if not any(isinstance(item, dict) and item.get("code") == "E-HISTORY-NOT-FOUND" for item in errors):
            errors.insert(0, {
                "code": "E-HISTORY-NOT-FOUND",
                "message": "未找到 .sysml-viz/history/index.json；请传 history_dir，"
                           "或先把模型视图 tab 打开让插件记录基线。",
            })
        result["errors"] = errors
    return result


def dispatch(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """按工具名分发，供本地调用模式使用。"""
    if tool_name == "validate_model_json":
        return call_validate_model_json(
            arguments.get("model"), arguments.get("use_json_schema")
        )
    if tool_name == "generate_sysml":
        return call_generate_sysml(
            arguments.get("model"),
            indent=arguments.get("indent", "    "),
            include_header=arguments.get("include_header", True),
        )
    if tool_name == "query_model":
        accepted = {
            key: value
            for key, value in arguments.items()
            if key in {"keyword", "query", "kind", "referrers_of", "duplicates",
                       "unsatisfied_requirements", "details", "limit"}
        }
        return call_query_model(
            arguments.get("model"), path=arguments.get("path"), **accepted
        )
    if tool_name == "verify_sysml":
        return call_verify_sysml(
            arguments.get("text", ""),
            arguments.get("model"),
            official=arguments.get("official", False),
        )
    if tool_name == "patch_model":
        return call_patch_model(
            arguments.get("model"),
            arguments.get("ops"),
            validate=arguments.get("validate", True),
        )
    if tool_name == "traceability":
        return call_traceability(
            arguments.get("model"),
            focus=arguments.get("focus"),
            fmt=arguments.get("fmt", "json"),
        )
    if tool_name == "parse_sysml":
        return call_parse_sysml(arguments.get("text"))
    if tool_name == "export_simulink":
        return call_export_simulink(
            arguments.get("model"),
            fmt=arguments.get("fmt", "csv"),
            scope=arguments.get("scope", "all"),
        )
    if tool_name == "export_timeline":
        return call_export_timeline(
            history_dir=arguments.get("history_dir"),
            model_path=arguments.get("model_path"),
            output=arguments.get("output"),
            title=arguments.get("title"),
        )
    return {
        "ok": False,
        "error": "未知工具 `%s`；可用工具：%s。" % (tool_name, "、".join(TOOL_NAMES)),
        "availableTools": TOOL_NAMES,
    }


# --------------------------------------------------------------------------------------
# MCP 封装
# --------------------------------------------------------------------------------------


def make_auth_middleware(token: str):
    """生成一个纯 ASGI 的 Bearer 鉴权中间件类（仅 http 传输需要）。

    ``__init__`` 故意接收 ``*args, **kwargs``：实测 fastmcp 会以
    ``cls(app, <额外参数>)`` 的形式实例化传入的中间件类，签名写死成
    ``__init__(self, app)`` 会直接报
    ``BearerAuthMiddleware.__init__() takes 2 positional arguments but 3 were given``
    （服务器照样"起来"，但每个请求都返回一条 JSON-RPC 错误）。多收的实参我们用不到，
    吸收掉即可。
    """

    expected = "Bearer " + token

    class BearerAuthMiddleware:  # noqa: D401
        def __init__(self, app, *_extra, **_kwargs):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope.get("type") != "http":
                await self.app(scope, receive, send)
                return
            headers = {k.decode("latin-1").lower(): v for k, v in (scope.get("headers") or [])}
            presented = headers.get("authorization", b"").decode("latin-1")
            if presented != expected:
                body = json.dumps(
                    {"error": "unauthorized", "detail": "缺少或错误的 Authorization: Bearer <token>"},
                    ensure_ascii=False,
                ).encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json; charset=utf-8"),
                            (b"content-length", str(len(body)).encode("ascii")),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            await self.app(scope, receive, send)

    return BearerAuthMiddleware


def import_fastmcp():
    """返回 (FastMCP, 来源说明)；都不可用时返回 (None, 原因)。"""
    try:
        from fastmcp import FastMCP  # type: ignore

        return FastMCP, "fastmcp"
    except Exception:  # noqa: BLE001
        pass
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore

        return FastMCP, "mcp.server.fastmcp"
    except Exception as exc:  # noqa: BLE001
        return None, "fastmcp 与 mcp 均不可用（%s）" % exc


def build_server(auth_token: Optional[str]):
    FastMCP, source = import_fastmcp()
    if FastMCP is None:
        return None, source

    # 注意：**不**通过 FastMCP 的 `middleware=` 参数挂鉴权。
    # 实测该参数期望的是另一套中间件协议（传类会报 "takes 2 positional arguments but 3
    # were given"，传实例又会报 "can't be used in 'await' expression"）。
    # 改为在 HTTP 传输层自己包一层纯 ASGI 中间件——见 serve_streamable_http()。
    kwargs: Dict[str, Any] = {
        "name": SERVER_NAME,
        "instructions": INSTRUCTIONS,
        "version": SERVER_VERSION,
    }

    try:
        server = FastMCP(**kwargs)
    except TypeError:
        server = FastMCP(name=SERVER_NAME)

    @server.tool(
        name="validate_model_json",
        description=SPEC_BY_NAME["validate_model_json"]["description"],
    )
    def _validate_model_json(model: dict, use_json_schema: Optional[bool] = None) -> dict:
        return call_validate_model_json(model, use_json_schema)

    @server.tool(
        name="generate_sysml",
        description=SPEC_BY_NAME["generate_sysml"]["description"],
    )
    def _generate_sysml(model: dict, indent: str = "    ", include_header: bool = True) -> dict:
        return call_generate_sysml(model, indent=indent, include_header=include_header)

    @server.tool(
        name="query_model",
        description=SPEC_BY_NAME["query_model"]["description"],
    )
    def _query_model(
        model: Optional[dict] = None,
        path: Optional[str] = None,
        keyword: Optional[str] = None,
        query: Optional[str] = None,
        kind: Optional[str] = None,
        referrers_of: Optional[str] = None,
        duplicates: bool = False,
        unsatisfied_requirements: bool = False,
        details: bool = False,
        limit: int = 200,
    ) -> dict:
        return call_query_model(
            model,
            path=path,
            keyword=keyword,
            query=query,
            kind=kind,
            referrers_of=referrers_of,
            duplicates=duplicates,
            unsatisfied_requirements=unsatisfied_requirements,
            details=details,
            limit=limit,
        )

    @server.tool(
        name="verify_sysml",
        description=SPEC_BY_NAME["verify_sysml"]["description"],
    )
    def _verify_sysml(
        text: str, model: Optional[dict] = None, official: bool = False
    ) -> dict:
        return call_verify_sysml(text, model, official=official)

    @server.tool(
        name="patch_model",
        description=SPEC_BY_NAME["patch_model"]["description"],
    )
    def _patch_model(model: dict, ops: List[dict], validate: bool = True) -> dict:
        return call_patch_model(model, ops, validate=validate)

    @server.tool(
        name="traceability",
        description=SPEC_BY_NAME["traceability"]["description"],
    )
    def _traceability(
        model: dict,
        focus: Optional[Union[str, List[str]]] = None,
        fmt: str = "json",
    ) -> dict:
        return call_traceability(model, focus=focus, fmt=fmt)

    @server.tool(
        name="parse_sysml",
        description=SPEC_BY_NAME["parse_sysml"]["description"],
    )
    def _parse_sysml(text: str) -> dict:
        return call_parse_sysml(text)

    @server.tool(
        name="export_simulink",
        description=SPEC_BY_NAME["export_simulink"]["description"],
    )
    def _export_simulink(model: dict, fmt: str = "csv", scope: str = "all") -> dict:
        return call_export_simulink(model, fmt=fmt, scope=scope)

    @server.tool(
        name="export_timeline",
        description=SPEC_BY_NAME["export_timeline"]["description"],
    )
    def _export_timeline(
        history_dir: Optional[str] = None,
        model_path: Optional[str] = None,
        output: Optional[str] = None,
        title: Optional[str] = None,
    ) -> dict:
        return call_export_timeline(
            history_dir=history_dir, model_path=model_path, output=output, title=title
        )

    return server, source


# --------------------------------------------------------------------------------------
# 本地调用模式（没有 MCP 依赖时的等价退路）
# --------------------------------------------------------------------------------------


#: ``--input`` 里出现这些键时，说明给的是「完整工具入参对象」而不是裸 IR 模型。
#: 裸 IR 模型的顶层只有 schema / package / elements / meta，与它们不冲突。
_LOCAL_ARGUMENT_KEYS = frozenset(
    {
        "model",
        "text",
        "path",
        "ops",
        "focus",
        "fmt",
        "keyword",
        "query",
        "kind",
        "referrers_of",
        "duplicates",
        "unsatisfied_requirements",
        "details",
        "limit",
        "use_json_schema",
        "indent",
        "include_header",
        "validate",
        "official",
        "scope",
        "history_dir",
        "model_path",
        "output",
        "title",
    }
)


def _looks_like_arguments(payload: Dict[str, Any]) -> bool:
    return any(key in _LOCAL_ARGUMENT_KEYS for key in payload)


def run_local_mode(args: argparse.Namespace) -> int:
    if args.list_tools:
        print(json.dumps({"server": SERVER_NAME, "version": SERVER_VERSION,
                          "mode": "local", "tools": TOOL_SPECS},
                         ensure_ascii=False, indent=2))
        return 0

    if not args.call:
        print(
            "未检测到 MCP 依赖（fastmcp / mcp），已切换到本地调用模式。\n"
            "  python run_server.py --list-tools                  # 列出工具契约\n"
            "  python run_server.py --call <tool> --input <file|JSON> [--text <SysML文本>]\n"
            "也可先安装依赖以获得 MCP 协议外壳：pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 3

    arguments: Dict[str, Any] = {}
    if args.input:
        parsed = _parse_input(args.input)
        if parsed is None:
            print(
                json.dumps(
                    {"ok": False, "error": "--input 既不是存在的文件，也不是合法 JSON 文本。"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        # 两种写法都支持：
        #   --input ir.json                          直接给一个 IR 模型
        #   --input '{"model": {...}, "limit": 5}'   给完整的工具入参对象
        #   --input '{"path": "ir.json"}'            给 path（query_model）
        arguments = parsed if _looks_like_arguments(parsed) else {"model": parsed}
    if args.text is not None:
        arguments["text"] = args.text
    # --model-file 与 --text 可以同时给：verify_sysml 需要「文本 + IR」才能做元素级比对。
    # 只有当 model / path 已经由 --input 提供时才不覆盖。
    if args.model_file and "model" not in arguments and "path" not in arguments:
        arguments["model"] = load_model(args.model_file)

    result = dispatch(args.call, arguments)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", False) else 1


def _parse_input(raw: str) -> Optional[Dict[str, Any]]:
    """``--input`` 既接受文件路径，也接受内联 JSON 文本。

    先看它像不像 JSON（避免把一长串 JSON 当路径去 ``stat``——在 macOS 上会抛
    ``OSError: File name too long``）；否则再当路径处理，并对 ``OSError`` 兜底。
    """
    stripped = raw.strip()
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(stripped)
        except Exception as exc:  # noqa: BLE001
            print(
                json.dumps(
                    {"ok": False, "error": "无法解析内联 JSON：%s" % exc},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return None
        return parsed if isinstance(parsed, dict) else {"model": parsed}

    try:
        candidate = Path(raw)
        is_file = candidate.is_file()
    except (OSError, ValueError):
        is_file = False

    if is_file:
        try:
            parsed = load_model(candidate)
        except Exception as exc:  # noqa: BLE001
            print(
                json.dumps(
                    {"ok": False, "error": "无法读取 %s：%s" % (candidate, exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return None
        return parsed if isinstance(parsed, dict) else {"model": parsed}

    try:
        parsed = json.loads(stripped)
    except Exception:  # noqa: BLE001
        return None
    return parsed if isinstance(parsed, dict) else {"model": parsed}


# --------------------------------------------------------------------------------------


def ensure_query_root_default() -> Optional[str]:
    """streamable-http 启动时给 ``SYSML_QUERY_ROOT`` 一个默认的目录边界。

    云端部署不该让调用方用 ``path`` 读服务端任意文件，所以未显式设置该变量时，
    把**当前工作目录**设为根（``query_model`` 的 ``path`` 只能读它下面的文件）。
    返回一句给启动日志用的提示；已经设置过（或显式设为空以外的值）时返回 ``None``，
    不动调用方的环境。**stdio 模式不调用本函数**，本地开发行为保持「不限制」。
    """
    if os.environ.get("SYSML_QUERY_ROOT"):
        return None
    default_root = os.getcwd()
    os.environ["SYSML_QUERY_ROOT"] = default_root
    return (
        "[sysml-modeling-agent] SYSML_QUERY_ROOT 未设置，已默认设为服务工作目录：%s"
        "（query_model 的 path 只能读该目录下的文件；需要更大范围请显式设置该变量）"
        % default_root
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_server.py",
        description="sysml-modeling-agent —— MCP 工具服务"
        "（validate / generate / query / verify / patch / trace / parse / export / timeline）",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="传输方式（默认 stdio；streamable-http 用于云端接入）",
    )
    parser.add_argument("--port", type=int, default=8000, help="HTTP 端口（默认 8000）")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP 绑定地址（默认 127.0.0.1，仅本机回环；如需局域网访问显式传 --host 0.0.0.0）",
    )
    parser.add_argument(
        "--auth-token",
        default=None,
        help="可选；仅 streamable-http 模式校验 Authorization: Bearer <token>",
    )
    parser.add_argument("--list-tools", action="store_true", help="列出工具契约后退出")
    parser.add_argument("--call", default=None, help="本地调用模式：工具名")
    parser.add_argument("--input", default=None, help="本地调用模式：JSON 文件路径或内联 JSON")
    parser.add_argument("--text", default=None, help="本地调用模式：直接给 SysML v2 文本")
    parser.add_argument("--model-file", default=None, help="本地调用模式：IR JSON 文件路径")
    parser.add_argument("--version", action="version", version="%(prog)s " + SERVER_VERSION)
    args = parser.parse_args(argv)

    server, source = build_server(args.auth_token)
    local_only = args.list_tools or args.call

    if server is None:
        if not local_only:
            print("[sysml-modeling-agent] %s" % source, file=sys.stderr)
        if args.transport == "streamable-http" and not local_only:
            print(
                "[sysml-modeling-agent] 无法以 streamable-http 启动：缺少 MCP 依赖。"
                "请先 `pip install -r requirements.txt`。",
                file=sys.stderr,
            )
            return 4
        return run_local_mode(args)

    if local_only:
        return run_local_mode(args)

    if args.transport == "stdio":
        if args.auth_token:
            print(
                "[sysml-modeling-agent] 提示：--auth-token 仅在 streamable-http 模式下校验；"
                "stdio 模式已忽略。",
                file=sys.stderr,
            )
        print("[sysml-modeling-agent] stdio 启动（MCP 框架：%s）" % source, file=sys.stderr)
        server.run(transport="stdio", show_banner=False)
        return 0

    # streamable-http：query_model 的 `path` 需要一个目录边界。云端不该让客户端读任意路径，
    # 所以未显式设置 SYSML_QUERY_ROOT 时，把**服务工作目录**设为默认根，并在启动输出里提示。
    # stdio 模式不动（本地开发保持原行为：不限制）。
    root_notice = ensure_query_root_default()
    if root_notice:
        print(root_notice, file=sys.stderr)


    if args.auth_token:
        print(
            "[sysml-modeling-agent] streamable-http 鉴权已启用：要求 "
            "Authorization: Bearer <token>",
            file=sys.stderr,
        )
    else:
        print(
            "[sysml-modeling-agent] 警告：未设置 --auth-token，服务对任何请求开放。"
            "公网暴露前请务必设置。",
            file=sys.stderr,
        )
    print(
        "[sysml-modeling-agent] streamable-http 监听 http://%s:%d/mcp （MCP 框架：%s）"
        % (args.host, args.port, source),
        file=sys.stderr,
    )
    return serve_streamable_http(server, args.host, args.port, args.auth_token)


# --------------------------------------------------------------------------------------
# streamable-http 传输：自己起 ASGI + 自己包鉴权（不依赖框架的中间件接口）
# --------------------------------------------------------------------------------------

#: 各框架暴露 ASGI app 的方法名，按可用性依次尝试
_HTTP_APP_BUILDERS = ("http_app", "streamable_http_app", "sse_app")


def serve_streamable_http(
    server: Any,
    host: str,
    port: int,
    auth_token: Optional[str],
) -> int:
    """以 Streamable HTTP 提供服务，并在设置了 token 时强制 Bearer 鉴权。

    实现取向：**自己拿 ASGI app、自己包中间件、自己起 uvicorn**。
    这样「鉴权」这件事完全在我们控制之下，不依赖 MCP 框架的中间件协议
    （两代框架的中间件接口不一致，实测都挂不上，见 build_server 的注释）。
    """
    app = _build_asgi_app(server)
    if app is None:
        print(
            "[sysml-modeling-agent] 无法取得 ASGI app，退回框架自带 run()；"
            "此时 --auth-token 不生效。",
            file=sys.stderr,
        )
        server.run(
            transport="streamable-http", show_banner=False, host=host, port=port
        )
        return 0

    if auth_token:
        app = make_auth_middleware(auth_token)(app)
        print(
            "[sysml-modeling-agent] streamable-http 鉴权已启用：要求 "
            "Authorization: Bearer <token>",
            file=sys.stderr,
        )
    else:
        print(
            "[sysml-modeling-agent] 警告：未设置 --auth-token，服务对任何请求开放。"
            "公网暴露前请务必设置。",
            file=sys.stderr,
        )

    print(
        "[sysml-modeling-agent] streamable-http 监听 http://%s:%d/mcp" % (host, port),
        file=sys.stderr,
    )

    try:
        import uvicorn  # type: ignore
    except Exception:  # noqa: BLE001
        print(
            "[sysml-modeling-agent] 未安装 uvicorn，退回框架自带 run()；"
            "此时 --auth-token 不生效。请 `pip install uvicorn` 以启用鉴权。",
            file=sys.stderr,
        )
        server.run(
            transport="streamable-http", show_banner=False, host=host, port=port
        )
        return 0

    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def _build_asgi_app(server: Any):
    """从 MCP 框架实例上取到 Streamable HTTP 的 ASGI app；取不到返回 None。"""
    for name in _HTTP_APP_BUILDERS:
        builder = getattr(server, name, None)
        if not callable(builder):
            continue
        for kwargs in (
            {"transport": "streamable-http"},
            {"transport": "streamable-http", "path": "/mcp"},
            {},
        ):
            try:
                return builder(**kwargs)
            except TypeError:
                continue
            except Exception:  # noqa: BLE001
                continue
    return None


if __name__ == "__main__":
    raise SystemExit(main())
