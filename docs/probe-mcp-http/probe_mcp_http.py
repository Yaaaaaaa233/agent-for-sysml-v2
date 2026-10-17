#!/usr/bin/env python3
"""MCP Streamable HTTP 客户端探针 —— 用真实协议跑一遍我们的工具服务。

用途：验证 `run_server.py --transport streamable-http` 真的能按 MCP 协议被调用，
以及 `--auth-token` 真的在拦人。只用标准库，跨平台。

用法：

    # 终端 A：起服务
    python run_server.py --transport streamable-http --port 8000 --auth-token <token>

    # 终端 B：跑探针
    python docs/probe-mcp-http/probe_mcp_http.py --url http://127.0.0.1:8000/mcp \
        --token <token> --ir docs/demo/step4-final.ir.json

退出码：0 = 全部符合预期；1 = 有不符合预期的项。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

EXPECTED_TOOLS = {
    "validate_model_json",
    "generate_sysml",
    "query_model",
    "verify_sysml",
}

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print("  [%s] %s%s" % (mark, label, ("  -> " + detail) if detail else ""))
    if not condition:
        failures.append(label)


def post(url: str, payload: Optional[Dict[str, Any]], token: Optional[str],
         session: Optional[str] = None) -> Tuple[int, Dict[str, str], str]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else b""
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json, text/event-stream")
    # 注意：带 session 的请求**同样**要带 token——实测两者缺一不可。
    if token:
        request.add_header("Authorization", "Bearer " + token)
    if session:
        request.add_header("mcp-session-id", session)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            return response.status, headers, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
        return exc.code, headers, exc.read().decode("utf-8", "replace")


def unwrap(body: str) -> Dict[str, Any]:
    """SSE 或裸 JSON 都能解析。"""
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    try:
        return json.loads(body)
    except Exception:  # noqa: BLE001
        return {"__raw__": body[:400]}


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP Streamable HTTP 客户端探针")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--token", default=None)
    parser.add_argument("--ir", default="docs/demo/step4-final.ir.json")
    args = parser.parse_args()

    print("== MCP Streamable HTTP 探针 ==")
    print("   url   :", args.url)
    print("   token :", "已提供" if args.token else "（无）")
    print()

    # ---- 1. 鉴权 ---------------------------------------------------------------
    if args.token:
        print("1) 鉴权")
        status, _, body = post(args.url, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=None)
        check("无 Authorization 头被拒绝", status == 401, "HTTP %s" % status)
        status, _, _ = post(args.url, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token="wrong-token")
        check("错误 token 被拒绝", status == 401, "HTTP %s" % status)
        status, _, _ = post(args.url, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=args.token + "-extra")
        check("超集 token 不被前缀匹配接受", status == 401, "HTTP %s" % status)
        print()

    # ---- 2. initialize ---------------------------------------------------------
    print("2) MCP initialize")
    status, headers, body = post(
        args.url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "probe-mcp-http", "version": "1.0.0"},
            },
        },
        token=args.token,
    )
    payload = unwrap(body)
    result = payload.get("result", {})
    info = result.get("serverInfo", {})
    session = headers.get("mcp-session-id")
    check("initialize 成功", status == 200 and bool(result), "HTTP %s" % status)
    check("serverInfo.name 正确", info.get("name") == "sysml-modeling-agent", json.dumps(info, ensure_ascii=False))
    check("拿到 mcp-session-id", bool(session), str(session))
    if not result:
        print("\n原始响应：", body[:400])
        return 1
    print()

    post(args.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, token=args.token, session=session)

    # ---- 3. tools/list ---------------------------------------------------------
    print("3) tools/list")
    status, _, body = post(args.url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                           token=args.token, session=session)
    tools = [t["name"] for t in unwrap(body).get("result", {}).get("tools", [])]
    check("四个工具都注册了", set(tools) == EXPECTED_TOOLS, str(tools))
    print()

    # ---- 4. tools/call ---------------------------------------------------------
    print("4) tools/call")
    try:
        model = json.load(open(args.ir, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("  无法读取 IR %s：%s" % (args.ir, exc))
        return 1

    def call(name: str, arguments: Dict[str, Any], call_id: int) -> Dict[str, Any]:
        status, _, body = post(
            args.url,
            {"jsonrpc": "2.0", "id": call_id, "method": "tools/call",
             "params": {"name": name, "arguments": arguments}},
            token=args.token,
            session=session,
        )
        result = unwrap(body).get("result", {})
        content = result.get("content") or [{}]
        try:
            return json.loads(content[0].get("text", "{}"))
        except Exception:  # noqa: BLE001
            return {"__raw__": content[0].get("text", "")[:300]}

    validation = call("validate_model_json", {"model": model}, 3)
    check("validate_model_json ok", validation.get("ok") is True,
          "errors=%d warnings=%d" % (len(validation.get("errors", [])), len(validation.get("warnings", []))))

    generated = call("generate_sysml", {"model": model}, 4)
    check("generate_sysml ok", generated.get("ok") is True, "sha256=%s" % str(generated.get("sha256"))[:16])

    queried = call("query_model", {"model": model, "unsatisfied_requirements": True}, 5)
    check("query_model ok", queried.get("ok") is True, "未被满足的需求=%s" % queried.get("count"))

    verified = call("verify_sysml", {"text": generated.get("text", ""), "model": model}, 6)
    check("verify_sysml ok", verified.get("ok") is True,
          json.dumps(verified.get("counts", {}), ensure_ascii=False))

    print()
    if failures:
        print("== 有 %d 项不符合预期 ==" % len(failures))
        for item in failures:
            print("   -", item)
        return 1
    print("== 全部符合预期 ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
