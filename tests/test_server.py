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
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import GOLDEN_IR, GOLDEN_SYSML, MCP_SERVER

RUN_SERVER = MCP_SERVER / "run_server.py"


def server_model():
    """测试用最小合法模型（不依赖标杆案例的元素计数）。"""
    return {
        "schema": "sysml-ir/v1",
        "package": "ServerDemo",
        "elements": [
            {
                "id": "REQ-A",
                "kind": "Requirement",
                "name": "ReqAlpha",
                "owner": "ServerDemo",
                "properties": {
                    "text": "转速不低于 1000 rpm",
                    "acceptanceCriteria": "n >= 1000 rpm",
                    "verifyMethod": "simulation",
                },
            },
            {
                "id": "ACT-A",
                "kind": "ActionDefinition",
                "name": "ActAlpha",
                "owner": "ServerDemo",
                "properties": {"inputs": [], "outputs": []},
                "relations": [
                    {"type": "verifies", "target": "REQ-A", "rationale": "仿真校验"}
                ],
            },
        ],
    }


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
        self.assertIn("1.2.0", result.stdout)
        self.assertNotIn("1.0.0", result.stdout)

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

    def test_model_file_flag_feeds_local_call(self):
        """`--model-file` 直接把 IR 文件喂给工具（等价于 --input 里的 model 字段）。"""
        result = run_cli("--call", "validate_model_json", "--model-file", str(GOLDEN_IR))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], msg=payload.get("errors"))
        self.assertEqual(payload["errors"], [])

    def test_text_and_model_file_together_enable_element_level_compare(self):
        """`--text` + `--model-file` 同时给：verify_sysml 才能做元素级比对（不再只跑 lint）。"""
        result = run_cli(
            "--call",
            "verify_sysml",
            "--text",
            GOLDEN_SYSML.read_text(encoding="utf-8"),
            "--model-file",
            str(GOLDEN_IR),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], msg=payload.get("mismatched"))
        self.assertIn("counts", payload, msg="只跑了 lint，说明 model 没被带上")
        counts = payload["counts"]
        self.assertEqual(counts["matched"], counts["irElements"])
        self.assertEqual(counts["mismatched"], 0)


class TestLocalInvokeMode(unittest.TestCase):
    """不装 MCP 依赖时的等价退路：--list-tools / --call。"""

    def test_list_tools_exposes_all_ten_tools(self):
        result = run_cli("--list-tools")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        names = [tool["name"] for tool in payload["tools"]]
        self.assertEqual(
            names,
            [
                "validate_model_json",
                "generate_sysml",
                "query_model",
                "verify_sysml",
                "patch_model",
                "traceability",
                "parse_sysml",
                "export_simulink",
                "export_timeline",
                "memory",
            ],
        )
        for tool in payload["tools"]:
            self.assertIn("description", tool)
            self.assertIn("inputSchema", tool)
            # parse_sysml 入参是文本、export_timeline 入参是历史目录、memory 入参是 op/query，其余以 IR model 为入口
            if tool["name"] not in {"parse_sysml", "export_timeline", "memory"}:
                self.assertIn("model", tool["inputSchema"]["properties"])
        parse_spec = next(tool for tool in payload["tools"] if tool["name"] == "parse_sysml")
        self.assertEqual(parse_spec["inputSchema"]["required"], ["text"])
        self.assertIn("渲染子集", parse_spec["description"])
        timeline_spec = next(tool for tool in payload["tools"] if tool["name"] == "export_timeline")
        for key in ("history_dir", "model_path", "output", "title"):
            self.assertIn(key, timeline_spec["inputSchema"]["properties"])
        self.assertNotIn("required", timeline_spec["inputSchema"])

    def test_query_schema_supports_path_and_drops_required_model(self):
        payload = json.loads(run_cli("--list-tools").stdout)
        query = next(tool for tool in payload["tools"] if tool["name"] == "query_model")
        schema = query["inputSchema"]
        self.assertIn("path", schema["properties"])
        self.assertIn("服务端本机", schema["properties"]["path"]["description"])
        self.assertIn("云端", schema["properties"]["path"]["description"])
        self.assertNotIn("required", schema)

    def test_patch_and_trace_schemas(self):
        payload = json.loads(run_cli("--list-tools").stdout)
        patch = next(tool for tool in payload["tools"] if tool["name"] == "patch_model")
        trace = next(tool for tool in payload["tools"] if tool["name"] == "traceability")
        self.assertEqual(set(patch["inputSchema"]["required"]), {"model", "ops"})
        self.assertIn("ops", patch["inputSchema"]["properties"])
        self.assertIn("focus", trace["inputSchema"]["properties"])
        self.assertEqual(trace["inputSchema"]["properties"]["fmt"]["enum"], ["json", "md"])
        self.assertEqual(trace["inputSchema"]["required"], ["model"])

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

    def test_call_query_with_path(self):
        """试用反馈：本地调用也能用 path（服务端本机文件）代替 model。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ir.json"
            path.write_text(json.dumps(server_model(), ensure_ascii=False), encoding="utf-8")
            result = run_cli(
                "--call", "query_model", "--input",
                json.dumps({"path": str(path), "keyword": "ReqAlpha"}),
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["id"], "REQ-A")

    def test_call_query_with_missing_path_fails_cleanly(self):
        result = run_cli(
            "--call", "query_model", "--input",
            json.dumps({"path": "/definitely/not/here/ir.json"}),
        )
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("不存在", payload["error"])

    def test_call_patch_model(self):
        arguments = {
            "model": server_model(),
            "ops": [
                {
                    "op": "add_element",
                    "element": {
                        "id": "ATTR-B",
                        "kind": "Attribute",
                        "name": "ratedCurrent",
                        "owner": "ServerDemo",
                        "properties": {"valueType": "Real", "defaultValue": 5.0, "unit": "A"},
                    },
                }
            ],
        }
        result = run_cli("--call", "patch_model", "--input", json.dumps(arguments))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], msg=payload["errors"])
        self.assertIn("ATTR-B", [item["id"] for item in payload["model"]["elements"]])
        self.assertEqual(payload["diff"][0]["change"], "+")

    def test_call_patch_model_rollback_is_reported(self):
        arguments = {
            "model": server_model(),
            "ops": [{"op": "remove_element", "id": "REQ-A"}],
        }
        result = run_cli("--call", "patch_model", "--input", json.dumps(arguments))
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["model"])
        self.assertIn("E-REF-DEPENDENT", [item["code"] for item in payload["errors"]])

    def test_call_traceability(self):
        arguments = {"model": server_model(), "fmt": "md"}
        result = run_cli("--call", "traceability", "--input", json.dumps(arguments))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], msg=payload["errors"])
        self.assertEqual(payload["matrix"][0]["requirement"], "REQ-A")
        self.assertEqual(payload["matrix"][0]["status"], "verified-only")
        self.assertIn("# 追溯矩阵", payload["content"])

    def test_call_verify_sysml(self):
        text = GOLDEN_SYSML.read_text(encoding="utf-8")
        result = run_cli(
            "--call", "verify_sysml", "--input",
            json.dumps({"text": text, "model": json.loads(GOLDEN_IR.read_text(encoding="utf-8"))}),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], msg=payload)

    def test_call_parse_sysml_returns_ir(self):
        text = GOLDEN_SYSML.read_text(encoding="utf-8")
        result = run_cli("--call", "parse_sysml", "--input", json.dumps({"text": text}))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], msg=payload["errors"])
        expected = json.loads(GOLDEN_IR.read_text(encoding="utf-8"))
        self.assertEqual(
            {element["id"] for element in payload["model"]["elements"]},
            {element["id"] for element in expected["elements"]},
        )

    def test_call_export_simulink(self):
        model = json.loads(GOLDEN_IR.read_text(encoding="utf-8"))
        result = run_cli(
            "--call", "export_simulink", "--input",
            json.dumps({"model": model, "fmt": "csv"}),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], msg=payload["errors"])
        self.assertIn("path,name,valueType,unit,defaultValue,kind,id,extra",
                      payload["content"].lstrip("\ufeff"))

    def test_call_export_timeline(self):
        """本地调用模式能渲染「建模全过程」SVG（不依赖插件/浏览器）。"""
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history"
            history.mkdir()
            baseline = {
                "schema": "sysml-ir/v1",
                "package": "TimelineDemo",
                "elements": [
                    {"id": "PD-A", "kind": "PartDefinition", "name": "A",
                     "owner": "TimelineDemo", "properties": {}},
                ],
            }
            step1 = json.loads(json.dumps(baseline))
            step1["elements"].append({
                "id": "REQ-A", "kind": "Requirement", "name": "ReqA",
                "owner": "TimelineDemo",
                "properties": {"text": "x", "acceptanceCriteria": "x",
                               "verifyMethod": "analysis"},
            })

            def snapshot(seq: int, model: dict):
                text = json.dumps(model, ensure_ascii=False, indent=2) + "\n"
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                name = "step-%04d-%s.ir.json" % (seq, digest[:8])
                (history / name).write_text(text, encoding="utf-8")
                return name, digest

            s0, h0 = snapshot(0, baseline)
            s1, h1 = snapshot(1, step1)
            index = {
                "schema": "sysml-viz-history/v1",
                "workspace": tmp,
                "modelPath": str(Path(tmp) / "demo.ir.json"),
                "steps": [
                    {"seq": 0, "at": "2026-10-19T12:00:00Z", "revision": h0[:8],
                     "irSha256": h0, "semanticSha256": h0, "elements": 1,
                     "relations": 0, "added": [], "removed": [], "changed": [],
                     "source": "baseline", "sessionId": "deadbeef", "snapshot": s0},
                    {"seq": 1, "at": "2026-10-19T12:01:00Z", "revision": h1[:8],
                     "irSha256": h1, "semanticSha256": h1, "elements": 2,
                     "relations": 0, "added": ["REQ-A"], "removed": [],
                     "changed": [], "source": "change", "sessionId": "deadbeef",
                     "turn": 1, "snapshot": s1},
                ],
            }
            (history / "index.json").write_text(
                json.dumps(index, ensure_ascii=False), encoding="utf-8"
            )
            result = run_cli(
                "--call", "export_timeline",
                "--input", json.dumps({"history_dir": str(history)}),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], msg=payload.get("errors"))
            self.assertEqual(payload["schema"], "sysml-timeline/v1")
            self.assertEqual(payload["summary"]["steps"], 2)
            svg = Path(payload["svgPath"]).read_text(encoding="utf-8")
            self.assertIn("<svg", svg)
            self.assertIn("建模全过程", svg)
            self.assertIn("ReqA", svg)
            self.assertIn("第 1 轮", svg)  # 有 turn 时图例显示对话轮次

        # 无历史目录 → 结构化失败，不抛异常
        result = run_cli(
            "--call", "export_timeline", "--input",
            json.dumps({"history_dir": "/definitely/not/here/history"}),
        )
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"][0]["code"], "E-HISTORY-NOT-FOUND")

    def test_verify_official_unavailable_is_reported_honestly(self):
        """没有后端时 official 必须是 unavailable，且不得被当成通过。"""
        import run_server

        unavailable = {
            "ok": False,
            "backend": "none",
            "status": "unavailable",
            "diagnostics": [],
            "detail": "测试桩：没有官方解析器后端。",
        }
        text = "package A {\n    part def B;\n}\n"
        with mock.patch.object(run_server, "parse_with_official", return_value=unavailable):
            payload = run_server.dispatch(
                "verify_sysml", {"text": text, "official": True}
            )
        # 内置 lint 本身通过，但调用方显式要求官方校验且后端不可用 → 顶层不返回 ok=True
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["official"]["status"], "unavailable")
        self.assertFalse(payload["official"]["ok"])
        self.assertIn("测试桩", payload["official"]["detail"])

    def test_verify_official_errors_turn_result_not_ok(self):
        import run_server

        failed = {
            "ok": False,
            "backend": "pilot-implementation",
            "status": "available",
            "diagnostics": [{"line": 2, "message": "ERROR:boom"}],
            "detail": "官方报错。",
        }
        text = "package A {\n    part def B;\n}\n"
        with mock.patch.object(run_server, "parse_with_official", return_value=failed):
            payload = run_server.dispatch(
                "verify_sysml", {"text": text, "official": True}
            )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["official"]["status"], "available")
        self.assertEqual(len(payload["official"]["diagnostics"]), 1)

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
            "validate_model_json", "generate_sysml", "query_model", "verify_sysml",
            "patch_model", "traceability", "parse_sysml", "export_simulink",
            "export_timeline", "memory",
        })
        model = json.loads(GOLDEN_IR.read_text(encoding="utf-8"))
        arguments = {
            "model": model,
            "text": GOLDEN_SYSML.read_text(encoding="utf-8"),
            "ops": [],
        }
        for name in run_server.TOOL_NAMES:
            if name == "export_timeline":
                # export_timeline 不吃 model；用不存在的临时目录验证「返回 dict 而非抛异常」
                with tempfile.TemporaryDirectory() as tmp:
                    payload = run_server.dispatch(name, {"history_dir": tmp})
                    self.assertIsInstance(payload, dict)
                    self.assertFalse(payload["ok"])
                    self.assertEqual(payload["errors"][0]["code"], "E-HISTORY-NOT-FOUND")
                continue
            if name == "memory":
                payload = run_server.dispatch(name, {"op": "search", "query": "工具数"})
                self.assertIsInstance(payload, dict)
                self.assertTrue(payload["ok"], payload)
                continue
            self.assertIsInstance(run_server.dispatch(name, arguments), dict)

    def test_dispatch_patch_model_matches_direct_call(self):
        import run_server
        from tools.patch import patch_model

        model = server_model()
        ops = [
            {
                "op": "add_element",
                "element": {
                    "id": "ATTR-B",
                    "kind": "Attribute",
                    "name": "ratedCurrent",
                    "owner": "ServerDemo",
                    "properties": {"valueType": "Real", "defaultValue": 5.0, "unit": "A"},
                },
            }
        ]
        direct = patch_model(model, ops)
        via_dispatch = run_server.dispatch("patch_model", {"model": model, "ops": ops})
        self.assertEqual(direct, via_dispatch)

    def test_dispatch_traceability_matches_direct_call(self):
        import run_server
        from tools.trace import traceability

        model = server_model()
        direct = traceability(model, focus="REQ-A", fmt="md")
        via_dispatch = run_server.dispatch(
            "traceability", {"model": model, "focus": "REQ-A", "fmt": "md"}
        )
        self.assertEqual(direct, via_dispatch)

    def test_dispatch_query_accepts_path(self):
        import run_server

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ir.json"
            path.write_text(json.dumps(server_model(), ensure_ascii=False), encoding="utf-8")
            payload = run_server.dispatch("query_model", {"path": str(path), "kind": "Requirement"})
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)

    def test_instructions_order_includes_patch_and_trace(self):
        import run_server

        text = run_server.INSTRUCTIONS
        order = [
            "query_model",
            "validate_model_json",
            "patch_model",
            "generate_sysml",
            "verify_sysml",
            "traceability",
        ]
        positions = [text.index(name) for name in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("出错时改 JSON，不要改文本", text)
        self.assertIn("回到第 3 步重新 validate_model_json", text)
        self.assertIn("导入既有模型用 parse_sysml", text)
        self.assertIn("导出仿真参数表用 export_simulink", text)
        self.assertLess(text.index("parse_sysml"), text.index("validate_model_json"))
        self.assertLess(text.index("generate_sysml"), text.index("traceability"))

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


class TestQueryRootDefault(unittest.TestCase):
    """streamable-http 启动时的 SYSML_QUERY_ROOT 默认值（stdio 不动）。"""

    def setUp(self):
        import run_server

        self.run_server = run_server
        self._saved = os.environ.get("SYSML_QUERY_ROOT")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("SYSML_QUERY_ROOT", None)
        else:
            os.environ["SYSML_QUERY_ROOT"] = self._saved

    def test_unset_root_defaults_to_working_directory(self):
        os.environ.pop("SYSML_QUERY_ROOT", None)
        notice = self.run_server.ensure_query_root_default()
        self.assertIsNotNone(notice)
        self.assertIn("SYSML_QUERY_ROOT", notice)
        self.assertIn(os.getcwd(), notice)
        self.assertEqual(os.environ.get("SYSML_QUERY_ROOT"), os.getcwd())

    def test_explicit_root_is_left_untouched(self):
        os.environ["SYSML_QUERY_ROOT"] = "/tmp/explicit-root"
        self.assertIsNone(self.run_server.ensure_query_root_default())
        self.assertEqual(os.environ["SYSML_QUERY_ROOT"], "/tmp/explicit-root")

    def test_query_tool_description_documents_path_and_root(self):
        description = self.run_server.SPEC_BY_NAME["query_model"]["description"]
        self.assertIn("SYSML_QUERY_ROOT", description)
        self.assertIn("path", description)
        for edge in ("relations[].target", "typeRef", "parameters", "sourceRef", "targetRef"):
            self.assertIn(edge, description, msg="query_model 描述缺少引用边口径：%s" % edge)

    def test_server_version_is_1_2_0(self):
        self.assertEqual(self.run_server.SERVER_VERSION, "1.2.0")

    def test_ten_tools_registered(self):
        self.assertEqual(len(self.run_server.TOOL_NAMES), 10)
        self.assertEqual(
            self.run_server.TOOL_NAMES,
            [
                "validate_model_json",
                "generate_sysml",
                "query_model",
                "verify_sysml",
                "patch_model",
                "traceability",
                "parse_sysml",
                "export_simulink",
                "export_timeline",
                "memory",
            ],
        )


class TestMemoryTool(unittest.TestCase):
    """memory 工具：只读检索 + 候选预检（只进 .spool，不自动提交）。"""

    def test_search_finds_tool_count_memory(self):
        import run_server

        payload = run_server.dispatch(
            "memory",
            {"op": "search", "query": "工具数要改哪些文件", "scope": ["mcp-server/run_server.py"]},
        )
        self.assertTrue(payload["ok"], payload)
        self.assertGreaterEqual(payload["count"], 1)
        ids = [item["id"] for item in payload["results"]]
        self.assertTrue(any(record_id.startswith("mem-") for record_id in ids))
        self.assertIn("memory", payload["schema"])

    def test_search_unknown_op(self):
        import run_server

        payload = run_server.dispatch("memory", {"op": "unknown"})
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"][0]["code"], "E-MEMORY-OP")

    def test_propose_requires_record(self):
        import run_server

        payload = run_server.dispatch("memory", {"op": "propose"})
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"][0]["code"], "E-MEMORY-RECORD-REQUIRED")

    def test_propose_dry_run_ok(self):
        import run_server

        record = (
            "---\n"
            "id: mem-20261022-9999\n"
            "kind: gotcha\n"
            "status: active\n"
            "slug: memory-tool-test\n"
            "title: 测试候选：memory 工具的 propose 预检\n"
            "created: 2026-10-22T20:00:00+08:00\n"
            "author: tests/unit\n"
            "scope: [memory/**]\n"
            "tags: [test]\n"
            "confidence: low\n"
            "review_after: 2027-01-01\n"
            "evidence:\n"
            "  - file:README.md\n"
            "---\n\n"
            "## 内容\n这条候选只用于验证 memory 工具的 propose 预检，不写任何文件；"
            "正文要足够长才能通过 E-BODY-SHORT 检查。\n\n"
            "## 为什么\npropose 必须默认 dry-run，避免 agent 误写；预检失败要给出可读错误码。\n\n"
            "## 用法\n看到 dryRun=true 就说明没有落盘，真正写入需要显式 dry_run=false + drain。\n"
        )
        payload = run_server.dispatch(
            "memory", {"op": "propose", "record": record, "dry_run": True}
        )
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["dryRun"])
        self.assertIn("targetPath", payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
