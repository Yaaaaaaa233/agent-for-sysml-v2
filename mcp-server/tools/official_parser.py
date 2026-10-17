"""``official_parser`` —— 官方 SysML v2 解析器（Pilot Implementation）的薄适配层。

**这一层做什么**：把「一段 SysML v2 文本」交给官方实现去解析，把它的输出折叠成
本项目统一的 ``{"ok", "backend", "status", "diagnostics", "detail"}`` 结构。本层
**只做进程编排与输出归一化**，不重新实现任何语法/语义判断。

**这一层不做什么（诚实边界）**：

- 它不会把「内置 ``sysml_lint`` 通过」冒充成「官方解析器通过」。后端不可用时
  一律返回 ``status="unavailable"``，``ok`` 恒为 ``False``——**没有后端就没有结论**。
- 它不保证官方实现一定接受本项目生成的文本；反过来也一样。官方解析器若报错，
  错误原样搬进 ``diagnostics``，不吞、不改写。

后端：``pilot-implementation``
==============================

官方仓库：https://github.com/Systems-Modeling/SysML-v2-Pilot-Implementation
（Eclipse Public License 2.0）。它是 JVM 上的 Xtext 实现，官方只发布 Eclipse 插件
与 Jupyter kernel 两种形态，**没有单独的 "parser.jar"**。

本适配层采用的入口是官方 kernel 发行包里自带的交互式类
``org.omg.sysml.interactive.SysMLInteractive``（kernel 的 ``kernel.json`` 同样用
``java -cp <dir>/*`` 这种方式启动它），命令形如：

.. code-block:: bash

    java -cp "<kernel 解包目录>/*" org.omg.sysml.interactive.SysMLInteractive <sysml.library 目录>

它启动后是一个 REPL：单行输入被当作模型文本解析；``%`` 单独一行则进入多行输入
模式，直到下一个单独的 ``%`` 行。因此我们把待解析文本包成：

.. code-block:: text

    %
    <SysML v2 文本>
    %
    %exit

从而**整段文本作为一次解析**进入官方实现（``SysMLInteractive.process``），
语法/语义错误由它自己判定。

探测顺序（``detect_backend``）：

1. ``$SYSML2_JAVA`` 指定的 java 可执行文件；
2. ``$JAVA_HOME/bin/java``；
3. 仓库内 ``docs/probe-official-parser/jre/Contents/Home/bin/java``（spike 下载的
   Temurin JRE，见该目录 EVIDENCE.txt）；
4. ``PATH`` 上的 ``java``——**必须真的能跑起来**才算数：macOS 的 ``/usr/bin/java``
   是个 stub，没装 JDK 时执行会以非零码退出，这种「假 java」必须排除。

classpath 探测顺序：``$SYSML2_CLASSPATH``（jar 列表，``:`` 分隔）→
``docs/probe-official-parser/kernel/lib/*.jar``（spike 解包 kernel 的产物）→
``docs/probe-official-parser/lib/*.jar``。

标准库目录：``$SYSML2_LIBRARY`` → ``docs/probe-official-parser/kernel/sysml.library``
→ ``docs/probe-official-parser/sysml.library``。没有标准库时官方实现仍能做**语法**
解析，但 ``Real`` / ``String`` 这类来自 ``ScalarValues`` 的名字会解析不到——这种
差异会如实出现在 ``detail`` 里。

实测状态（2026-10-17，证据见 ``docs/probe-official-parser/EVIDENCE.txt``）
==========================================================================

官方解析器**在本机可以跑通**：适配层能启动它、拿到逐条带行号的诊断，阳性对照
（带 ``private import ScalarValues::*;`` 的最小模型）返回 ``ok=True``。

当前生成器（补了标准库 import 头与 ``Wh`` → ``W*h`` 别名）的实测结果：
golden / ``base_model`` / ``extended_model`` 三份生成文本均 **0 条诊断**、
``ok=True``（EVIDENCE §13，2026-10-17）。这只覆盖**语法与引用解析**；
语义/建模质量未验证，**任何文档都不得把它写成整体的「官方验证通过」**。

同日早前（补 import 之前）golden 为 0 条语法错误 + 77 条标准库引用未解析诊断，
根因是缺 import 与官方库没有 ``Wh``（EVIDENCE §6–§8）。那组数字是历史状态，
不再代表当前生成器输出。

另有两个实测细节，影响本层的用法：

- REPL 的多行输入以**单独一行** ``%`` 结束，所以文本里不能出现这种行（本层直接
  拒绝并返回 ``unverified``，而不是截断后误报通过）；
- 本版官方语法**不接受裸 ``import``**：``import ScalarValues::*;`` 报
  ``mismatched input 'import' expecting '}'``，而 ``private import`` /
  ``public import`` 正常。这是实测现象，不是推断。

风格与 ``tools/sysml_lint.py`` 对齐：中文 docstring、类型注解、只用标准库。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: 适配层认识的后端名（``auto`` 只用于 ``parse_with_official`` 的入参）
BACKENDS: Tuple[str, ...] = ("pilot-implementation",)

#: 官方交互式入口的主类
PILOT_MAIN_CLASS = "org.omg.sysml.interactive.SysMLInteractive"

#: 子进程超时（秒）。官方实现启动 + 加载标准库通常 < 20 s，60 s 留足余量。
DEFAULT_TIMEOUT = 60.0

#: 仓库根（本文件位于 <repo>/mcp-server/tools/official_parser.py）
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: spike 证据目录（下载物都放这里，jar / JRE 不入 git）
PROBE_DIR = REPO_ROOT / "docs" / "probe-official-parser"

#: 探测时依次尝试的 kernel 解包目录相对路径（相对 PROBE_DIR）
CLASSPATH_DIR_CANDIDATES: Tuple[str, ...] = (
    "kernel/lib",
    "kernel",
    "lib",
)

#: 官方 SysML v2 标准库可作为 ``SysMLInteractive.main`` 首个参数的目录
LIBRARY_CANDIDATES: Tuple[str, ...] = ("kernel/sysml.library", "sysml.library")

#: 官方实现（Xtext）的实际报错形态，已实测：
#: ``ERROR:no viable alternative at input '}' (1.sysml line : 4 column : 5)``
_PILOT_LOCATION = re.compile(
    r"\((?P<file>[^()\s]+)\s+line\s*:\s*(?P<line>\d+)\s+column\s*:\s*(?P<column>\d+)\)"
)

#: 兜底：``file.sysml:12:5`` 这类 Xtext 常见定位写法
_LOCATED = re.compile(
    r"(?:(?P<file>[^\s:]*\.(?:sysml|kerml)):)?(?P<line>\d+):(?P<column>\d+)?[:\s]"
)


def detect_backend() -> Dict[str, Any]:
    """探测本机是否有可用的官方解析器后端。**只读**，不下载、不启动解析。

    :return: ``{"backend", "available", "detail", "evidence_path"}``；
        ``backend`` 为 ``"pilot-implementation"`` 或 ``"none"``（无后端），
        ``detail`` 用人话说明探测到了什么、缺什么，
        ``evidence_path`` 指向 spike 证据文件（存在时）否则 ``None``。
    """
    evidence = PROBE_DIR / "EVIDENCE.txt"
    evidence_path = str(evidence) if evidence.is_file() else None

    java = _find_java()
    if java is None:
        return {
            "backend": "none",
            "available": False,
            "detail": (
                "未找到可运行的 java：$SYSML2_JAVA、$JAVA_HOME、"
                "docs/probe-official-parser/jre 与 PATH 都没有可用的 JVM"
                "（macOS 的 /usr/bin/java 在未装 JDK 时只是 stub，执行即失败）。"
            ),
            "evidence_path": evidence_path,
        }

    jars = _find_classpath_jars()
    if not jars:
        return {
            "backend": "none",
            "available": False,
            "detail": (
                "找到 java（%s），但没有官方实现的 classpath：可用 $SYSML2_CLASSPATH 指定，"
                "或把 kernel 发行包解到 %s。" % (java, PROBE_DIR / "kernel")
            ),
            "evidence_path": evidence_path,
        }

    library = _find_library()
    return {
        "backend": "pilot-implementation",
        "available": True,
        "detail": "java=%s；classpath 共 %d 个 jar；标准库=%s"
        % (java, len(jars), str(library) if library else "未找到（仅语法可查）"),
        "evidence_path": evidence_path,
    }


def parse_with_official(text: str, backend: str = "auto") -> Dict[str, Any]:
    """用官方 SysML v2 实现解析一段文本。

    :param text: 待解析的 SysML v2 文本（UTF-8 字符串）。
    :param backend: ``"auto"`` / ``"pilot-implementation"`` / ``"none"``。
        非法取值抛 ``ValueError``——这是**调用方写错**，不是环境问题。
    :return: ``{"ok", "backend", "status", "diagnostics", "detail"}``：

        - ``ok``：仅当官方实现真的跑完、且**没有报出任何 error** 时为 ``True``；
        - ``status``：``"available"``（跑完并有结论）/``"unavailable"``（没有后端）/
          ``"unverified"``（有后端但没拿到可信结论：超时、崩溃、输出不可解析、
          入口用法不支持等）；
        - ``diagnostics``：**只收 error**，``[{"line": int|None, "message": str}, ...]``；
          官方实现给出的 warning 不计入这里（数量写在 ``detail`` 里）；
        - ``detail``：人话说明发生了什么（含实际命令与退出码的关键信息）。

    本函数**不抛**环境类异常：找不到后端、子进程超时/崩溃都折叠进返回值。
    """
    if backend not in ("auto", "none") + BACKENDS:
        raise ValueError(
            "未知的 backend：%r；合法取值为 'auto'、'none' 或 %s。"
            % (backend, "、".join(repr(name) for name in BACKENDS))
        )

    selection = detect_backend()

    if backend == "none":
        return _unavailable("none", "调用方显式指定 backend='none'，不做官方解析。")
    if not selection["available"]:
        return _unavailable(selection["backend"], selection["detail"])

    java = _find_java()
    jars = _find_classpath_jars()
    library = _find_library()
    if java is None or not jars:  # 探测与执行之间环境变化，按不可用处理
        return _unavailable("none", "探测到后端后环境发生变化：java 或 classpath 已不可用。")

    text_type_error = _check_text(text)
    if text_type_error is not None:
        return {
            "ok": False,
            "backend": "pilot-implementation",
            "status": "unverified",
            "diagnostics": [{"line": None, "message": text_type_error}],
            "detail": "输入不是字符串，未调用官方解析器。",
        }

    if _has_lone_percent_line(text):
        return {
            "ok": False,
            "backend": "pilot-implementation",
            "status": "unverified",
            "diagnostics": [
                {
                    "line": None,
                    "message": "文本里有一行只含 '%'，与 REPL 的多行输入结束标记冲突。",
                }
            ],
            "detail": (
                "官方交互入口以单独一行 '%' 结束多行输入；为避免把文本截断后误报通过，"
                "本适配层拒绝解析这种文本。"
            ),
        }

    outcome = _run_pilot(text, java=java, jars=jars, library=library, timeout=DEFAULT_TIMEOUT)
    if outcome["timedOut"]:
        return {
            "ok": False,
            "backend": "pilot-implementation",
            "status": "unverified",
            "diagnostics": [
                {"line": None, "message": "官方解析器超过 %.0f 秒未返回，已强制终止。" % DEFAULT_TIMEOUT}
            ],
            "detail": "命令：%s；超时时间：%.0f s。" % (outcome["command"], DEFAULT_TIMEOUT),
        }

    diagnostics = _extract_diagnostics(outcome["stdout"], outcome["stderr"])
    command = outcome["command"]
    warnings = _count_warnings(outcome["stdout"])
    warn_note = "；另有 %d 条 warning（官方实现报出，未计入 diagnostics）" % warnings if warnings else ""

    if outcome["returncode"] != 0:
        return {
            "ok": False,
            "backend": "pilot-implementation",
            "status": "unverified",
            "diagnostics": diagnostics
            or [{"line": None, "message": "官方解析器以退出码 %d 结束，且没有可识别的错误输出。" % outcome["returncode"]}],
            "detail": "命令：%s；退出码：%d。" % (command, outcome["returncode"]),
        }

    if outcome["stdout"].strip() == "" and outcome["stderr"].strip() == "":
        return {
            "ok": False,
            "backend": "pilot-implementation",
            "status": "unverified",
            "diagnostics": [{"line": None, "message": "官方解析器没有任何输出，无法判断结果。"}],
            "detail": "命令：%s；退出码：0，但 stdout/stderr 均为空。" % command,
        }

    if diagnostics:
        return {
            "ok": False,
            "backend": "pilot-implementation",
            "status": "available",
            "diagnostics": diagnostics,
            "detail": "命令：%s；官方实现报出 %d 条错误%s。" % (command, len(diagnostics), warn_note),
        }

    return {
        "ok": True,
        "backend": "pilot-implementation",
        "status": "available",
        "diagnostics": [],
        "detail": "命令：%s；官方实现未报错（退出码 0）%s。" % (command, warn_note),
    }


# --------------------------------------------------------------------------------------
# 后端探测
# --------------------------------------------------------------------------------------


def _find_java() -> Optional[str]:
    """返回一个**真的能跑起来**的 java 可执行文件路径，找不到返回 ``None``。"""
    candidates: List[str] = []
    explicit = os.environ.get("SYSML2_JAVA")
    if explicit:
        candidates.append(explicit)
    home = os.environ.get("JAVA_HOME")
    if home:
        candidates.append(str(Path(home) / "bin" / "java"))
    local = PROBE_DIR / "jre" / "Contents" / "Home" / "bin" / "java"
    candidates.append(str(local))
    candidates.append(str(PROBE_DIR / "jre" / "bin" / "java"))
    found = shutil.which("java")
    if found:
        candidates.append(found)

    for candidate in candidates:
        path = Path(candidate)
        if not path.is_file() or not os.access(str(path), os.X_OK):
            continue
        try:
            probe = subprocess.run(
                [str(path), "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return str(path)
    return None


def _find_classpath_jars() -> List[str]:
    """返回官方实现的 jar 清单（用于 ``java -cp``）；没有则空列表。"""
    explicit = os.environ.get("SYSML2_CLASSPATH")
    if explicit:
        return [item for item in explicit.split(os.pathsep) if item]

    for relative in CLASSPATH_DIR_CANDIDATES:
        directory = PROBE_DIR / relative
        if directory.is_dir():
            jars = sorted(str(path) for path in directory.glob("*.jar"))
            if jars:
                return jars
    return []


def _find_library() -> Optional[str]:
    """返回 SysML v2 标准库目录（``Kernel Libraries`` 等的父目录）。"""
    explicit = os.environ.get("SYSML2_LIBRARY")
    if explicit:
        return explicit if Path(explicit).is_dir() else None
    for relative in LIBRARY_CANDIDATES:
        directory = PROBE_DIR / relative
        if directory.is_dir():
            return str(directory)
    return None


# --------------------------------------------------------------------------------------
# 子进程编排
# --------------------------------------------------------------------------------------


def _build_command(java: str, jars: Sequence[str], library: Optional[str]) -> List[str]:
    """拼出官方交互式入口的启动命令。"""
    classpath = os.pathsep.join(jars)
    command = [
        java,
        "-Xmx1024m",
        "-Djava.awt.headless=true",
        "-cp",
        classpath,
        PILOT_MAIN_CLASS,
    ]
    if library:
        command.append(library)
    return command


def _run_pilot(
    text: str,
    java: str,
    jars: Sequence[str],
    library: Optional[str],
    timeout: float,
) -> Dict[str, Any]:
    """启动官方 REPL，把 ``text`` 作为一次多行输入喂进去。**不抛异常**。"""
    command = _build_command(java, jars, library)
    script = "%%\n%s\n%%\n%%exit\n" % (text.rstrip("\n"),)
    # 说明：格式化串里的 %% 会变成字面量 %：一个 % 开始多行输入、一个 % 结束它，
    # 最后的 %exit 让 REPL 退出。

    env = dict(os.environ)
    env.setdefault("LANG", "en_US.UTF-8")
    env.setdefault("LC_ALL", "en_US.UTF-8")

    with tempfile.TemporaryDirectory(prefix="sysml2-probe-") as workdir:
        try:
            completed = subprocess.run(
                command,
                input=script.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
                env=env,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as expired:
            return {
                "timedOut": True,
                "returncode": None,
                "command": _pretty(command),
                "stdout": _decode(expired.stdout),
                "stderr": _decode(expired.stderr),
            }
        except OSError as exc:
            return {
                "timedOut": False,
                "returncode": 127,
                "command": _pretty(command),
                "stdout": "",
                "stderr": "启动官方解析器失败：%s" % exc,
            }

    return {
        "timedOut": False,
        "returncode": completed.returncode,
        "command": _pretty(command),
        "stdout": _decode(completed.stdout),
        "stderr": _decode(completed.stderr),
    }


def _pretty(command: Sequence[str]) -> str:
    """命令的展示形态：含空格的参数加单引号，便于从日志里原样复制复现。"""
    return " ".join(_quote(part) for part in command)


def _quote(value: str) -> str:
    return "'%s'" % value if " " in value else value


def _decode(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, bytes):
        return payload.decode("utf-8", "replace")
    return str(payload)


# --------------------------------------------------------------------------------------
# 输出归一化
# --------------------------------------------------------------------------------------


def _extract_diagnostics(stdout: str, stderr: str) -> List[Dict[str, Any]]:
    """从官方实现的输出里抽出错误条目。

    官方实现（Xtext）把语法/语义问题逐条打印，实测形态：:

        ERROR:no viable alternative at input '}' (1.sysml line : 4 column : 5)

    这里按「带 error 关键字」的行做保守识别，并尽量解析出行号；认不出的行不臆测成
    错误（宁可 ``unverified``，不可谎报 ``ok``）。REPL 的 ``1> `` 提示符与
    ``Reading ...`` 进度行不会命中。
    """
    diagnostics: List[Dict[str, Any]] = []
    seen = set()
    for line in (stdout + "\n" + stderr).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if "error" not in lowered and "exception" not in lowered:
            continue
        # REPL 提示符与正文粘在同一行（``1> ERROR:...``），先剥掉提示符
        message = re.sub(r"^\d+>\s*", "", stripped).strip()
        line_number: Optional[int] = None
        pilot_location = _PILOT_LOCATION.search(message)
        if pilot_location is not None:
            try:
                line_number = int(pilot_location.group("line"))
            except (TypeError, ValueError):
                line_number = None
        else:
            located = _LOCATED.search(message)
            if located is not None and located.group("line"):
                try:
                    line_number = int(located.group("line"))
                except (TypeError, ValueError):
                    line_number = None
        if (line_number, message) in seen:
            continue
        seen.add((line_number, message))
        diagnostics.append({"line": line_number, "message": message})
    return diagnostics


def _count_warnings(stdout: str) -> int:
    """数官方输出里的 ``WARNING:`` 行（只用于 ``detail`` 提示，不影响 ``ok``）。"""
    return sum(
        1
        for line in stdout.splitlines()
        if re.sub(r"^\d+>\s*", "", line.strip()).startswith("WARNING:")
    )


def _check_text(text: Any) -> Optional[str]:
    """检查入参类型；返回错误说明或 ``None``。"""
    if isinstance(text, str):
        return None
    return "输入必须是 str，收到 %s。" % type(text).__name__


def _has_lone_percent_line(text: str) -> bool:
    return any(line.strip() == "%" for line in text.splitlines())


def _unavailable(backend: str, detail: str) -> Dict[str, Any]:
    """构造「没有后端」的统一返回。``ok`` 必须为 ``False``。"""
    return {
        "ok": False,
        "backend": backend,
        "status": "unavailable",
        "diagnostics": [],
        "detail": detail,
    }


# --------------------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import json

    if len(sys.argv) < 2:
        print("用法：python -m tools.official_parser <model.sysml>")
        print(json.dumps(detect_backend(), ensure_ascii=False, indent=2))
        raise SystemExit(2)
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        content = handle.read()
    result = parse_with_official(content)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 1)
