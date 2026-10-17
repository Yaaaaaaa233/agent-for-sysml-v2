"""``tools.official_parser`` 的契约测试。

覆盖点（全部**不依赖网络、不依赖 JVM**，CI 里也能跑）：

- ``detect_backend`` 在「无 JVM / 有 JVM 无 classpath / 两者都有」三种环境下的返回结构；
- ``parse_with_official`` 在没有后端时**优雅**返回 ``unavailable``：``ok`` 恒为
  ``False``、``diagnostics`` 形状正确、不抛裸异常、不偷偷调用子进程；
- 后端参数非法时**明确报错**（``ValueError``，不是静默降级）；
- 有后端但拿不到可信结论（超时 / 崩溃 / 空输出）时是 ``unverified`` 而不是 ``ok``；
- 官方输出的错误行能被归一化成 ``{"line", "message"}``；
- 官方实现真的 0 错误时才返回 ``ok=True``。

这里所有「后端」都是 mock 出来的，**没有**真的启动 java——真机证据在
``docs/probe-official-parser/EVIDENCE.txt``。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "mcp-server") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "mcp-server"))

from tools import official_parser  # noqa: E402

DETECT_KEYS = {"backend", "available", "detail", "evidence_path"}
RESULT_KEYS = {"ok", "backend", "status", "diagnostics", "detail"}

#: 官方实现真实的报错形态（实测，见 EVIDENCE.txt）
PILOT_ERROR_OUTPUT = (
    "SysML v2 Pilot Implementation\n"
    "1> ERROR:no viable alternative at input '}' (1.sysml line : 4 column : 5)\n"
    "ERROR:Couldn't resolve reference to Type 'Real'. (1.sysml line : 9 column : 39)\n"
    "2> "
)


def _patched(java="/fake/java", jars=("/fake/lib.jar",), library=None):
    """同时替换三个探测函数，模拟指定后端环境。"""
    return [
        mock.patch.object(official_parser, "_find_java", return_value=java),
        mock.patch.object(
            official_parser, "_find_classpath_jars", return_value=list(jars)
        ),
        mock.patch.object(official_parser, "_find_library", return_value=library),
    ]


class _BackendCase(unittest.TestCase):
    """带一个「把环境改成指定状态」的小工具。"""

    def set_backend(self, available: bool, **kwargs):
        if available:
            patchers = _patched(**kwargs)
        else:
            patchers = _patched(java=None, jars=())
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_run(self, **outcome):
        """替换 ``_run_pilot``，返回给定的「子进程结果」。"""
        payload = {
            "timedOut": False,
            "returncode": 0,
            "command": "java -cp ... " + official_parser.PILOT_MAIN_CLASS,
            "stdout": "",
            "stderr": "",
        }
        payload.update(outcome)
        patcher = mock.patch.object(official_parser, "_run_pilot", return_value=payload)
        patcher.start()
        self.addCleanup(patcher.stop)
        return patcher


class DetectBackendTest(_BackendCase):
    """``detect_backend`` 的返回结构与环境判定。"""

    def test_without_jvm_is_unavailable(self):
        self.set_backend(False)
        result = official_parser.detect_backend()
        self.assertEqual(set(result), DETECT_KEYS)
        self.assertEqual(result["backend"], "none")
        self.assertIs(result["available"], False)
        self.assertIsInstance(result["detail"], str)
        self.assertTrue(result["detail"])
        self.assertTrue(
            result["evidence_path"] is None
            or isinstance(result["evidence_path"], str)
        )

    def test_java_without_classpath_is_unavailable(self):
        self.set_backend(True, jars=())
        result = official_parser.detect_backend()
        self.assertEqual(result["backend"], "none")
        self.assertIs(result["available"], False)
        self.assertIn("classpath", result["detail"])

    def test_full_backend_is_available(self):
        self.set_backend(True, library="/fake/sysml.library")
        result = official_parser.detect_backend()
        self.assertEqual(set(result), DETECT_KEYS)
        self.assertEqual(result["backend"], "pilot-implementation")
        self.assertIs(result["available"], True)
        self.assertIn("/fake/java", result["detail"])
        self.assertIn("/fake/sysml.library", result["detail"])

    def test_evidence_path_points_to_existing_file_when_present(self):
        self.set_backend(False)
        result = official_parser.detect_backend()
        if result["evidence_path"] is not None:
            self.assertTrue(Path(result["evidence_path"]).is_file())


class ParseUnavailableTest(_BackendCase):
    """没有后端时的契约：不抛异常、不谎报 ok、不启动子进程。"""

    def test_no_backend_returns_unavailable(self):
        self.set_backend(False)
        boom = mock.patch.object(
            official_parser,
            "_run_pilot",
            side_effect=AssertionError("没有后端时不允许启动子进程"),
        )
        boom.start()
        self.addCleanup(boom.stop)

        result = official_parser.parse_with_official("package Demo { part def A; }")
        self.assertEqual(set(result), RESULT_KEYS)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["backend"], "none")
        self.assertIsInstance(result["detail"], str)
        self.assertTrue(result["detail"])

    def test_explicit_none_backend_is_unavailable(self):
        self.set_backend(True)
        result = official_parser.parse_with_official("package D {}", backend="none")
        self.assertIs(result["ok"], False)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["backend"], "none")

    def test_invalid_backend_raises_value_error(self):
        self.set_backend(False)
        with self.assertRaises(ValueError) as caught:
            official_parser.parse_with_official("package D {}", backend="pysysml2")
        message = str(caught.exception)
        self.assertIn("pysysml2", message)
        self.assertIn("pilot-implementation", message)

    def test_non_string_text_is_unverified_not_crash(self):
        self.set_backend(True)
        result = official_parser.parse_with_official(None)  # type: ignore[arg-type]
        self.assertIs(result["ok"], False)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertIsNone(result["diagnostics"][0]["line"])

    def test_lone_percent_line_is_rejected_without_running(self):
        self.set_backend(True)
        boom = mock.patch.object(
            official_parser,
            "_run_pilot",
            side_effect=AssertionError("含 '%' 行的文本不应进入官方 REPL"),
        )
        boom.start()
        self.addCleanup(boom.stop)

        result = official_parser.parse_with_official("package D {\n%\n}")
        self.assertIs(result["ok"], False)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(len(result["diagnostics"]), 1)


class ParseWithBackendTest(_BackendCase):
    """有后端时的结果归一化。"""

    def test_success_returns_ok_true(self):
        self.set_backend(True)
        self.fake_run(
            stdout="SysML v2 Pilot Implementation\n1> Package Demo (uuid)\n2> "
        )
        result = official_parser.parse_with_official("package Demo {\n}")
        self.assertIs(result["ok"], True)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["diagnostics"], [])
        self.assertEqual(result["backend"], "pilot-implementation")

    def test_official_errors_become_diagnostics(self):
        self.set_backend(True)
        self.fake_run(stdout=PILOT_ERROR_OUTPUT)
        result = official_parser.parse_with_official("package Demo {\n}")
        self.assertIs(result["ok"], False)
        self.assertEqual(result["status"], "available")
        self.assertEqual(len(result["diagnostics"]), 2)
        self.assertEqual(result["diagnostics"][0]["line"], 4)
        self.assertEqual(result["diagnostics"][1]["line"], 9)
        for item in result["diagnostics"]:
            self.assertEqual(set(item), {"line", "message"})
            self.assertIsInstance(item["message"], str)
            self.assertNotIn(item["message"], ("",))
            # REPL 提示符不应粘在消息里
            self.assertFalse(item["message"].startswith("1>"))

    def test_timeout_is_unverified(self):
        self.set_backend(True)
        self.fake_run(timedOut=True, returncode=None)
        result = official_parser.parse_with_official("package Demo {}")
        self.assertIs(result["ok"], False)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["diagnostics"][0]["line"], None)

    def test_crash_is_unverified(self):
        self.set_backend(True)
        self.fake_run(returncode=1, stderr="Exception in thread main: boom")
        result = official_parser.parse_with_official("package Demo {}")
        self.assertIs(result["ok"], False)
        self.assertEqual(result["status"], "unverified")
        self.assertTrue(result["diagnostics"])

    def test_empty_output_is_unverified(self):
        self.set_backend(True)
        self.fake_run(stdout="", stderr="")
        result = official_parser.parse_with_official("package Demo {}")
        self.assertIs(result["ok"], False)
        self.assertEqual(result["status"], "unverified")

    def test_no_error_output_never_reports_ok_false_positive(self):
        """只有进度输出、没有 error 行时，不应把进度当成错误。"""
        self.set_backend(True)
        self.fake_run(
            stdout="SysML v2 Pilot Implementation\nReading lib/A.sysml...\n1> Package P (u)\n2> "
        )
        result = official_parser.parse_with_official("package P {}")
        self.assertIs(result["ok"], True)
        self.assertEqual(result["diagnostics"], [])


class CommandTest(_BackendCase):
    """启动命令与 stdin 脚本的构造。"""

    def test_build_command_uses_official_entrypoint(self):
        command = official_parser._build_command(
            "/jre/bin/java", ["/k/all.jar"], "/k/sysml.library"
        )
        self.assertEqual(command[0], "/jre/bin/java")
        self.assertIn("-cp", command)
        self.assertIn("/k/all.jar", command)
        self.assertEqual(command[-1], "/k/sysml.library")
        self.assertIn(official_parser.PILOT_MAIN_CLASS, command)

    def test_repl_script_wraps_text_in_percent_block(self):
        captured = {}

        class _Completed:
            returncode = 0
            stdout = b"1> Package D (u)\n2> "
            stderr = b""

        def fake_subprocess_run(command, **kwargs):
            captured["command"] = command
            captured["input"] = kwargs.get("input")
            return _Completed()

        with mock.patch.object(official_parser.subprocess, "run", fake_subprocess_run):
            official_parser._run_pilot(
                "package D {\n    part def A;\n}",
                java="/jre/bin/java",
                jars=["/k/all.jar"],
                library=None,
                timeout=1.0,
            )

        script = captured["input"].decode("utf-8")
        self.assertTrue(script.startswith("%\n"))
        self.assertIn("package D {", script)
        self.assertTrue(script.rstrip("\n").endswith("%exit"))
        # 文本本身没有被改写
        self.assertIn("    part def A;", script)


if __name__ == "__main__":
    unittest.main()
