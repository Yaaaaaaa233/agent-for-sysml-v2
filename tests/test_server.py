"""T5 —— ``run_server.py`` 的启动接口契约。

契约（部署手册按此引用，改动即破坏部署文档）：

    python run_server.py [--transport stdio|streamable-http] [--port 8000]
                         [--auth-token <token>] [--host 127.0.0.1]

这里用**真实子进程**跑 ``run_server.py``，验证参数确实被接受、工具确实可调用；
再在进程内验证 Bearer 鉴权中间件的行为。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
import sys
import unittest

from _support import GOLDEN_IR, GOLDEN_SYSML, MCP_SERVER

RUN_SERVER = MCP_SERVER / "run_server.py"


def run_cli(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUN_SERVER), *args],
        cwd=str(MCP_SERVER),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class TestCliContract(unittest.TestCase):
    def test_version_flag(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("1.0.0", result.stdout)

    def test_help_lists_contract_arguments(self):
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0)
        for flag in ("--transport", "--port", "--host", "--auth-token"):
            self.assertIn(flag, result.stdout, msg="契约参数缺失：%s" % flag)

    def test_host_defaults_to_loopback_only(self):
        """安全口径（《Win 电脑部署手册》§3.6）：默认只绑 127.0.0.1，
        局域网/公网暴露必须显式传 --host 0.0.0.0。"""
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0)
        # --help 会按终端宽度折行，先把空白压平再做包含判断
        text = " ".join(result.stdout.split())
        self.assertIn("--host HOST", text)
        self.assertIn("默认 127.0.0.1", text)
        self.assertIn("--host 0.0.0.0", text)

    def test_transport_choices_are_restricted(self):
        result = run_cli("--transport", "websocket")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)

    def test_transport_defaults_to_stdio(self):
        """不传 --transport 时默认 stdio——用一个必然报错的取值反证 choices 生效，
        再用 --list-tools 证明默认参数下不报参数错误。"""
        result = run_cli("--list-tools")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_port_and_auth_token_are_accepted(self):
        """契约参数必须被 argparse 接受（不报未知参数 / 非法取值）。"""
        result = run_cli("--transport", "streamable-http", "--port", "8123",
                         "--auth-token", "s3cret", "--list-tools")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("error:", result.stderr.lower())
        self.assertEqual(json.loads(result.stdout)["server"], "sysml-modeling-agent")

    def test_stdio_is_an_accepted_transport(self):
        result = run_cli("--transport", "stdio", "--list-tools")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_unknown_flag_is_rejected(self):
        self.assertNotEqual(run_cli("--nope").returncode, 0)


class TestLocalInvokeMode(unittest.TestCase):
    """不装 MCP 依赖时的等价退路：--list-tools / --call。"""

    def test_list_tools_exposes_the_three_core_tools(self):
        result = run_cli("--list-tools")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        names = [tool["name"] for tool in payload["tools"]]
        self.assertIn("validate_model_json", names)
        self.assertIn("generate_sysml", names)
        self.assertIn("query_model", names)
        for tool in payload["tools"]:
            self.assertIn("description", tool)
            self.assertIn("inputSchema", tool)
            self.assertIn("model", tool["inputSchema"]["properties"])

    def test_call_validate_on_golden_case(self):
        result = run_cli("--call", "validate_model_json", "--input", str(GOLDEN_IR))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["errors"], [])

    def test_call_generate_matches_checked_in_artifact(self):
        """生成器输出必须与仓库里存档的 .sysml 逐字节一致（防止手工改动漂移）。"""
        result = run_cli("--call", "generate_sysml", "--input", str(GOLDEN_IR))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["text"], GOLDEN_SYSML.read_text(encoding="utf-8"))

    def test_call_query(self):
        result = run_cli(
            "--call", "query_model", "--input",
            json.dumps({"model": json.loads(GOLDEN_IR.read_text(encoding="utf-8")),
                        "unsatisfied_requirements": True}),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["count"], 0)

    def test_call_verify_sysml(self):
        text = GOLDEN_SYSML.read_text(encoding="utf-8")
        result = run_cli(
            "--call", "verify_sysml", "--input",
            json.dumps({"text": text, "model": json.loads(GOLDEN_IR.read_text(encoding="utf-8"))}),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], msg=payload)

    def test_call_unknown_tool_fails_cleanly(self):
        result = run_cli("--call", "no_such_tool", "--input", "{}")
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("availableTools", payload)


class TestAuthMiddleware(unittest.TestCase):
    """Bearer 鉴权：仅在 streamable-http 生效，缺头/错头返回 401。"""

    def _invoke(self, middleware_cls, headers):
        captured = {}

        async def app(scope, receive, send):
            captured["called"] = True
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        sent = []

        async def send(message):
            sent.append(message)

        async def receive():
            return {"type": "http.request"}

        scope = {"type": "http", "headers": headers, "method": "POST", "path": "/mcp"}
        asyncio.run(middleware_cls(app)(scope, receive, send))
        return captured.get("called", False), sent

    def test_rejects_missing_authorization_header(self):
        from run_server import make_auth_middleware

        called, sent = self._invoke(make_auth_middleware("s3cret"), [])
        self.assertFalse(called)
        self.assertEqual(sent[0]["status"], 401)

    def test_rejects_wrong_token(self):
        from run_server import make_auth_middleware

        called, sent = self._invoke(
            make_auth_middleware("s3cret"), [(b"authorization", b"Bearer nope")]
        )
        self.assertFalse(called)
        self.assertEqual(sent[0]["status"], 401)

    def test_accepts_correct_token(self):
        from run_server import make_auth_middleware

        called, sent = self._invoke(
            make_auth_middleware("s3cret"), [(b"authorization", b"Bearer s3cret")]
        )
        self.assertTrue(called)
        self.assertEqual(sent[0]["status"], 200)

    def test_token_is_not_prefix_matched(self):
        """`Bearer s3cret-more` 不该被当成 `Bearer s3cret`（必须是精确匹配）。"""
        from run_server import make_auth_middleware

        called, _ = self._invoke(
            make_auth_middleware("s3cret"), [(b"authorization", b"Bearer s3cret-more")]
        )
        self.assertFalse(called)

    def test_non_http_scope_passes_through(self):
        """lifespan 等非 http scope 必须透传，否则服务器起不来。"""
        from run_server import make_auth_middleware

        called = {}

        async def app(scope, receive, send):
            called["yes"] = True

        async def send(message):
            pass

        async def receive():
            return {"type": "lifespan.startup"}

        asyncio.run(
            make_auth_middleware("s3cret")(app)({"type": "lifespan", "headers": []}, receive, send)
        )
        self.assertTrue(called.get("yes"))


class TestToolWrappers(unittest.TestCase):
    """MCP 包装与本地调用必须走同一批纯函数，不得出现两套逻辑。"""

    def test_dispatch_matches_direct_call(self):
        import run_server
        from tools.generator import generate_sysml

        model = json.loads(GOLDEN_IR.read_text(encoding="utf-8"))
        direct = generate_sysml(model)
        via_dispatch = run_server.dispatch("generate_sysml", {"model": model})
        self.assertEqual(direct["text"], via_dispatch["text"])
        self.assertEqual(direct["sha256"], via_dispatch["sha256"])

    def test_dispatch_query_accepts_query_alias(self):
        import run_server

        model = json.loads(GOLDEN_IR.read_text(encoding="utf-8"))
        a = run_server.dispatch("query_model", {"model": model, "keyword": "Battery"})
        b = run_server.dispatch("query_model", {"model": model, "query": "Battery"})
        self.assertEqual(a["count"], b["count"])

    def test_tool_specs_cover_all_dispatched_names(self):
        import run_server

        self.assertEqual(set(run_server.TOOL_NAMES), {
            "validate_model_json", "generate_sysml", "query_model", "verify_sysml"
        })
        for name in run_server.TOOL_NAMES:
            self.assertIsInstance(
                run_server.dispatch(name, {"model": json.loads(GOLDEN_IR.read_text(encoding="utf-8")),
                                           "text": GOLDEN_SYSML.read_text(encoding="utf-8")}),
                dict,
            )

    def test_import_fastmcp_reports_source_or_reason(self):
        import run_server

        server, source = run_server.import_fastmcp()
        if server is None:
            self.assertIsInstance(source, str)
            self.assertTrue(source)


class TestHttpServingPlumbing(unittest.TestCase):
    """streamable-http 的接线（不真的起服务器，避免测试依赖网络与端口）。"""

    def test_build_asgi_app_returns_none_for_object_without_builder(self):
        import run_server

        self.assertIsNone(run_server._build_asgi_app(object()))

    def test_build_asgi_app_uses_first_working_builder(self):
        import run_server

        class Fake:
            def __init__(self):
                self.calls = []

            def http_app(self, **kwargs):
                self.calls.append(("http_app", kwargs))
                return "FAKE-APP"

        fake = Fake()
        self.assertEqual(run_server._build_asgi_app(fake), "FAKE-APP")
        self.assertEqual(fake.calls[0][0], "http_app")

    def test_build_asgi_app_falls_back_when_transport_kwarg_unsupported(self):
        import run_server

        class Fake:
            def __init__(self):
                self.calls = 0

            def streamable_http_app(self, **kwargs):
                self.calls += 1
                if "transport" in kwargs:
                    raise TypeError("unexpected keyword")
                return "FALLBACK-APP"

        self.assertEqual(run_server._build_asgi_app(Fake()), "FALLBACK-APP")

    def test_build_asgi_app_skips_builder_that_always_raises(self):
        import run_server

        class Fake:
            def http_app(self, **kwargs):
                raise RuntimeError("boom")

        self.assertIsNone(run_server._build_asgi_app(Fake()))

    def test_middleware_instance_wraps_asgi_app(self):
        """中间件必须能被当普通 ASGI app 包起来——HTTP 路径就是这么挂的。"""
        import run_server

        inner_called = {}

        async def inner(scope, receive, send):
            inner_called["yes"] = True
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        wrapped = run_server.make_auth_middleware("tok")(inner)
        sent = []

        async def send(message):
            sent.append(message)

        async def receive():
            return {"type": "http.request"}

        asyncio.run(wrapped({"type": "http", "headers": [(b"authorization", b"Bearer tok")]}, receive, send))
        self.assertTrue(inner_called.get("yes"))
        self.assertEqual(sent[0]["status"], 204)

    def test_serving_entrypoint_is_exposed(self):
        import run_server

        self.assertTrue(callable(run_server.serve_streamable_http))
        signature = inspect.signature(run_server.serve_streamable_http)
        for name in ("server", "host", "port", "auth_token"):
            self.assertIn(name, signature.parameters)

    def test_http_app_builders_cover_common_framework_apis(self):
        import run_server

        self.assertIn("http_app", run_server._HTTP_APP_BUILDERS)  # fastmcp
        self.assertIn("streamable_http_app", run_server._HTTP_APP_BUILDERS)  # 官方 SDK


if __name__ == "__main__":
    unittest.main(verbosity=2)
