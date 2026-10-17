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
from typing import Any, Dict, List, Optional

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

from tools.generator import generate_sysml  # noqa: E402
from tools.query import query_model  # noqa: E402
from tools.sysml_lint import lint_sysml, roundtrip_check  # noqa: E402
from tools.validator import load_model, validate_model_json  # noqa: E402

SERVER_NAME = "sysml-modeling-agent"
SERVER_VERSION = "1.0.0"

INSTRUCTIONS = """\
SysML v2 建模智能体（MVP）。核心路线是「LLM 填表、代码建模」：
你只产出/修改 IR JSON（结构化中间表示），确定性代码负责校验并渲染 SysML v2 文本。

固定顺序（不可打乱）：
1. query_model  先查现状——确认 id / 命名是否被占用、是否已有同类元素；
2. 产出或修改 IR JSON（schema = sysml-ir/v1）；
3. validate_model_json  改到 errors 为空；
4. generate_sysml  渲染 SysML v2 文本；
5. verify_sysml  回验（lint + 元素级比对）。

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
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "object"},
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
            "required": ["model"],
        },
    },
    {
        "name": "verify_sysml",
        "description": (
            "回验生成的 SysML v2 文本（MVP 的 parse 替代形态）：轻量语法自查"
            "（括号/注释/字符串/语句终结，均带行列定位）+ 声明抽取 + 与 IR 的元素级比对。"
            "方案 5.2 的 parse_sysml 双向解析列二期。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "SysML v2 文本"},
                "model": {"type": "object", "description": "可选：给出 IR 则做元素级比对"},
            },
            "required": ["text"],
        },
    },
]

TOOL_NAMES = [spec["name"] for spec in TOOL_SPECS]


# --------------------------------------------------------------------------------------
# 工具函数本体（与 MCP 框架无关，纯函数）
# --------------------------------------------------------------------------------------


def call_validate_model_json(model: Any, use_json_schema: Optional[bool] = None) -> Dict[str, Any]:
    return validate_model_json(model, use_json_schema=use_json_schema)


def call_generate_sysml(
    model: Any, indent: str = "    ", include_header: bool = True
) -> Dict[str, Any]:
    return generate_sysml(model, indent=indent, include_header=include_header)


def call_query_model(model: Any, **kwargs: Any) -> Dict[str, Any]:
    return query_model(model, **kwargs)


def call_verify_sysml(text: str, model: Any = None) -> Dict[str, Any]:
    if model is None:
        return lint_sysml(text)
    return roundtrip_check(model, text)


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
        return call_query_model(arguments.get("model"), **accepted)
    if tool_name == "verify_sysml":
        return call_verify_sysml(arguments.get("text", ""), arguments.get("model"))
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

    @server.tool(name="validate_model_json", description=TOOL_SPECS[0]["description"])
    def _validate_model_json(model: dict, use_json_schema: Optional[bool] = None) -> dict:
        return call_validate_model_json(model, use_json_schema)

    @server.tool(name="generate_sysml", description=TOOL_SPECS[1]["description"])
    def _generate_sysml(model: dict, indent: str = "    ", include_header: bool = True) -> dict:
        return call_generate_sysml(model, indent=indent, include_header=include_header)

    @server.tool(name="query_model", description=TOOL_SPECS[2]["description"])
    def _query_model(
        model: dict,
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
            keyword=keyword,
            query=query,
            kind=kind,
            referrers_of=referrers_of,
            duplicates=duplicates,
            unsatisfied_requirements=unsatisfied_requirements,
            details=details,
            limit=limit,
        )

    @server.tool(name="verify_sysml", description=TOOL_SPECS[3]["description"])
    def _verify_sysml(text: str, model: Optional[dict] = None) -> dict:
        return call_verify_sysml(text, model)

    return server, source


# --------------------------------------------------------------------------------------
# 本地调用模式（没有 MCP 依赖时的等价退路）
# --------------------------------------------------------------------------------------


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
        if "model" in parsed or "text" in parsed:
            arguments = parsed
        else:
            arguments = {"model": parsed}
    if args.text is not None:
        arguments["text"] = args.text
    if "model" not in arguments and "text" not in arguments and args.model_file:
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_server.py",
        description="sysml-modeling-agent —— MCP 工具服务（validate / generate / query / verify）",
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
