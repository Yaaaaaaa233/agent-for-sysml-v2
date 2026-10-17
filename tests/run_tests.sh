#!/usr/bin/env bash
# sysml-modeling-agent —— 一键跑全部测试（T5）
#
#   ./tests/run_tests.sh            全部用例，详细输出
#   ./tests/run_tests.sh -q         安静模式
#   PYTHON=python3.12 ./tests/run_tests.sh
#
# 只用标准库 unittest，不依赖 pytest。
# Windows 用户请用同目录的 run_tests.bat。

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"

# 优先用项目 venv（install.sh 建的），其次环境变量，最后 PATH 上的 python
if [ -n "${PYTHON:-}" ]; then
  PY="${PYTHON}"
elif [ -x "${ROOT}/.venv/bin/python" ]; then
  PY="${ROOT}/.venv/bin/python"
elif [ -x "${ROOT}/.venv/Scripts/python.exe" ]; then
  PY="${ROOT}/.venv/Scripts/python.exe"   # Windows (Git Bash / MSYS)
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi

if ! command -v "${PY}" >/dev/null 2>&1 && [ ! -x "${PY}" ]; then
  echo "找不到 Python 解释器（试过 PYTHON 环境变量、.venv、python3、python）" >&2
  exit 127
fi

echo "== sysml-modeling-agent 测试 =="
echo "   解释器 : ${PY}"
echo "   仓库根 : ${ROOT}"
echo

cd "${ROOT}"

# tests/ 作为顶层目录，因此测试里的 `import _support` 可用；
# mcp-server 通过 PYTHONPATH 暴露 `tools.*`（_support 里也兜了一层 sys.path）。
export PYTHONPATH="${ROOT}/mcp-server${PYTHONPATH:+:${PYTHONPATH}}"

exec "${PY}" -m unittest discover -s tests -t tests -p "test_*.py" "$@"
