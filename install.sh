#!/usr/bin/env bash
# =============================================================================
# sysml-modeling-agent —— 一键安装脚本
#
#   ./install.sh                 建 venv + 装依赖 + 把 skills/ 下的全部 skill 注册到 DSH
#   ./install.sh --copy          注册 skill 时用「复制」而不是「符号链接」
#   ./install.sh --skills-only   只注册 skill，不建 venv、不装依赖
#   ./install.sh --no-skills     只建 venv 装依赖，不碰 DSH skill 目录
#   ./install.sh --no-venv       跳过 venv，用系统 Python 装依赖
#   ./install.sh --print-config  只打印 DSH 的 MCP 配置片段（command 优先用 .venv 解释器），什么都不改
#   ./install.sh --help
#
# DSH 的注册方式依据 docs/T0-调研结论.md 的实测结论：
#   - skill 用户级根目录 = $DSH_HOME/skills（$DSH_HOME 默认 ~/.dsh）
#     格式：<name>/SKILL.md，YAML frontmatter 必填 name + description
#   - MCP 工具注册 = 在 profile 的 cordis.yml 里加一条
#     @deepseek-ai/dsh-mcp-client 插件条目（**本脚本不代改，只打印片段**）
#     片段字段形态与 docs/本机挂载试用指引.md §2.0 落位脚本逐字段一致：
#       command = $REPO/.venv/bin/python 绝对路径 / args = run_server.py 绝对路径 / cwd = mcp-server 目录
#
# 本脚本**不会**修改任何 DSH 配置文件。skill 目录是新建链接/副本，
# 不动已有内容；MCP 配置片段只打印出来供你手工粘贴。
# 片段里的 command 用 **.venv 解释器**：系统 python3 通常没装 MCP 依赖（fastmcp / mcp），
# 拿它当 command 会以 exit 3 静默起不来；.venv 缺失时片段里会给醒目的降级警告。
# =============================================================================

set -euo pipefail

SELF="$(basename "${BASH_SOURCE[0]}")"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# venv 解释器的绝对路径（MCP 依赖 fastmcp / mcp 装在 venv 里；系统 python3 通常没有）。
# 找不到时输出空串——MCP 配置片段据此给降级警告，而不是静默打印裸 python3。
venv_python() {
  if [ -x "${HERE}/.venv/bin/python" ]; then
    printf '%s\n' "${HERE}/.venv/bin/python"           # Linux / macOS
  elif [ -x "${HERE}/.venv/Scripts/python.exe" ]; then
    printf '%s\n' "${HERE}/.venv/Scripts/python.exe"   # Windows (Git Bash / MSYS)
  fi
}
VENV_PY="$(venv_python)"

# 发现 skills/*/SKILL.md（目录 bundle）。数量随仓库变化，不写死——
# 新增 skill 后 ./install.sh 与 --print-config 自动跟着变。
SKILL_NAMES=()
for _dir in "${HERE}"/skills/*/; do
  [ -f "${_dir}SKILL.md" ] || continue
  SKILL_NAMES+=("$(basename "${_dir%/}")")
done
SKILL_COUNT="${#SKILL_NAMES[@]}"

USE_COPY=0
DO_SKILLS=1
DO_VENV=1
PRINT_ONLY=0
SKILLS_ONLY=0

usage() {
  # 只打印文件头的注释块：从第 2 行的 ===== 分隔线开始，到与之配对的下一条 ===== 为止。
  # （旧实现写死行号 2,40p，头注释变短后会把代码一起打出来——这里改成按内容定界。）
  sed -n '2,/^# =====/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --copy)         USE_COPY=1 ;;
    --skills-only)  SKILLS_ONLY=1; DO_VENV=0; PRINT_ONLY=0 ;;
    --no-skills)    DO_SKILLS=0 ;;
    --no-venv)      DO_VENV=0 ;;
    --print-config) PRINT_ONLY=1 ;;
    -h|--help)      usage ;;
    *) echo "未知参数：$1（用 --help 看用法）" >&2; exit 2 ;;
  esac
  shift
done

echo "=============================================================="
echo " sysml-modeling-agent 安装"
echo "=============================================================="
echo " 仓库目录 : ${HERE}"
echo

# -----------------------------------------------------------------------------
# 0. 找 Python（3.10+，跨平台）
# -----------------------------------------------------------------------------
if [ -n "${PYTHON:-}" ]; then
  PY="${PYTHON}"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "[错误] 找不到 Python。请先安装 Python 3.10+ 并确保它在 PATH 上。" >&2
  exit 127
fi

PYVER="$("${PY}" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
PYMAJ="$("${PY}" -c 'import sys; print(sys.version_info[0])')"
PYMIN="$("${PY}" -c 'import sys; print(sys.version_info[1])')"
echo "[1/4] Python : ${PY} (${PYVER})"

if [ "${PYMAJ}" -lt 3 ] || { [ "${PYMAJ}" -eq 3 ] && [ "${PYMIN}" -lt 10 ]; }; then
  echo "[错误] 需要 Python 3.10 或更高版本，当前为 ${PYVER}。" >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# 1. venv + 依赖
# -----------------------------------------------------------------------------
if [ "${SKILLS_ONLY}" -eq 1 ] || [ "${PRINT_ONLY}" -eq 1 ]; then
  echo "[2/4] 跳过 venv 与依赖安装（--skills-only / --print-config）"
  TARGET_PY="${VENV_PY:-${PY}}"     # 已装好的 .venv 优先；没有才退回系统 Python
elif [ "${DO_VENV}" -eq 1 ]; then
  echo "[2/4] 创建虚拟环境 .venv"
  if [ -d "${HERE}/.venv" ]; then
    echo "      .venv 已存在，复用"
  else
    "${PY}" -m venv "${HERE}/.venv"
    echo "      已创建 ${HERE}/.venv"
  fi
  VENV_PY="$(venv_python)"
  if [ -z "${VENV_PY}" ]; then
    echo "[错误] venv 建好了但找不到解释器，请手工检查 ${HERE}/.venv" >&2
    exit 1
  fi
  TARGET_PY="${VENV_PY}"
else
  echo "[2/4] --no-venv：使用系统 Python"
  TARGET_PY="${PY}"
fi

if [ "${SKILLS_ONLY}" -eq 1 ] || [ "${PRINT_ONLY}" -eq 1 ]; then
  echo "[3/4] 跳过依赖安装"
elif [ "${PRINT_ONLY}" -eq 0 ]; then
  "${TARGET_PY}" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  echo "[3/4] 安装依赖（mcp-server/requirements.txt）"
  if "${TARGET_PY}" -m pip install -r "${HERE}/mcp-server/requirements.txt"; then
    echo "      依赖安装完成"
  else
    echo "      [警告] 依赖安装失败——**这不阻塞使用**。" >&2
    echo "        核心逻辑（校验/渲染/查询/回验）是纯标准库实现，一个依赖都不装也能跑：" >&2
    echo "          ${TARGET_PY} mcp-server/run_server.py --list-tools" >&2
    echo "          ${TARGET_PY} mcp-server/run_server.py --call validate_model_json --input <ir.json>" >&2
    echo "        只是没有 MCP 协议外壳（DSH/扣子无法直接挂载）。" >&2
  fi
fi

# -----------------------------------------------------------------------------
# 2. 注册 skill 到 DSH 用户级 skill 目录
# -----------------------------------------------------------------------------
DSH_HOME_RESOLVED="${DSH_HOME:-$HOME/.dsh}"
SKILLS_DST="${DSH_HOME_RESOLVED}/skills"

if [ "${DO_SKILLS}" -eq 1 ] && [ "${PRINT_ONLY}" -eq 0 ]; then
  echo "[4/4] 注册 skill 到 ${SKILLS_DST}"
  mkdir -p "${SKILLS_DST}"
  for dir in "${HERE}"/skills/*/; do
    [ -f "${dir}SKILL.md" ] || continue
    name="$(basename "${dir}")"
    target="${SKILLS_DST}/${name}"
    if [ -e "${target}" ] || [ -L "${target}" ]; then
      echo "      ${name}：已存在，跳过（如需覆盖请先手工删除 ${target}）"
      continue
    fi
    if [ "${USE_COPY}" -eq 1 ]; then
      cp -R "${dir%/}" "${target}"
      echo "      ${name}：已复制"
    else
      if ln -s "${dir%/}" "${target}" 2>/dev/null; then
        echo "      ${name}：已建立符号链接 → ${dir%/}"
      else
        cp -R "${dir%/}" "${target}"
        echo "      ${name}：符号链接不可用，已改为复制"
      fi
    fi
  done
  echo "      提示：DSH 会监视该目录，新增 skill 会在下一个模型步骤自动出现在 skill 目录中，无需重启。"
else
  echo "[4/4] 跳过 skill 注册"
  echo "      已发现 ${SKILL_COUNT} 份 skill（${SKILL_NAMES[*]}）"
  echo "      手工注册方式（DSH 用户级 skill 根目录，rank 400）："
  echo "        mkdir -p \"${SKILLS_DST}\""
  for _name in "${SKILL_NAMES[@]}"; do
    printf '        ln -s "%s/skills/%s" "%s/%s"\n' "${HERE}" "${_name}" "${SKILLS_DST}" "${_name}"
  done
  echo "      （Windows 无符号链接权限时改用复制：xcopy /E /I skills\\<name> %USERPROFILE%\\.dsh\\skills\\<name>）"
fi

# -----------------------------------------------------------------------------
# 3. 打印 DSH 的 MCP 配置片段（不代改配置）
# -----------------------------------------------------------------------------
SERVER_PY="${HERE}/mcp-server/run_server.py"
SERVER_CWD="${HERE}/mcp-server"

# 片段里的 command 必须是能跑 MCP 的解释器：系统 python3 通常没有 fastmcp / mcp，
# 拖进 cordis.yml 会以 exit 3 静默失败（"未检测到 MCP 依赖…切换到本地调用模式"），故优先 venv。
if [ -n "${VENV_PY}" ] && [ "${TARGET_PY}" = "${VENV_PY}" ]; then
  MCP_CMD_NOTE="    # command 用 .venv 里的解释器：MCP 依赖（fastmcp / mcp）装在这里"
elif [ -n "${VENV_PY}" ]; then
  MCP_CMD_NOTE="    # ⚠️ 当前是 --no-venv 的系统 Python；请确认它装了 mcp-server/requirements.txt，否则 MCP 服务起不来"
else
  MCP_CMD_NOTE="    # ⚠️ 未找到 .venv，先运行 bash install.sh 完成安装；下面的 command 仅为占位，直接粘贴会因缺 MCP 依赖起不来"
fi

cat <<EOF

==============================================================
 MCP 工具注册（需手工操作）
==============================================================
在 DSH profile 的 cordis.yml 里加一条插件条目。文件位置：

    \${DSH_HOME:-~/.dsh}/profiles/<profile>/cordis.yml

（本机实测：桌面端 profile 由 Electron 独占管理，无法用 CLI 转储或改写，
  请走 GUI 的插件设置页，或手工编辑该文件。详见 docs/T0-调研结论.md §1.5）

stdio 方式（本地推荐）：

- id: mcp-sysml-agent
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: sysml-agent
    transport: stdio
${MCP_CMD_NOTE}
    command: ${TARGET_PY}
    args: ['${SERVER_PY}']
    cwd: ${SERVER_CWD}

streamable-http 方式（公网 / 容器）：

- id: mcp-sysml-agent
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: sysml-agent
    transport: streamable-http
    url: http://<主机>:8000/mcp
    headers:
      Authorization: !!js '\`Bearer \${process.env.MCP_TOKEN}\`'

挂上之后，工具会以这些名字出现在模型面前：

    mcp__sysml-agent__validate_model_json
    mcp__sysml-agent__generate_sysml
    mcp__sysml-agent__query_model
    mcp__sysml-agent__verify_sysml
    mcp__sysml-agent__patch_model
    mcp__sysml-agent__traceability
    mcp__sysml-agent__parse_sysml
    mcp__sysml-agent__export_simulink

==============================================================
 验证
==============================================================
# 列出工具契约（不需要 MCP 依赖也能跑）
"${TARGET_PY}" "${SERVER_PY}" --list-tools

# 直接校验标杆案例
"${TARGET_PY}" "${SERVER_PY}" --call validate_model_json \\
    --input "${HERE}/examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json"

# 跑全部测试（当前 527 个用例；以实际输出为准）
"${HERE}/tests/run_tests.sh"

# 起 HTTP 服务（云端接入用；公网暴露前务必设置 --auth-token）
"${TARGET_PY}" "${SERVER_PY}" --transport streamable-http --port 8000 --auth-token <token>
EOF

echo
echo "安装完成。详见 README.md；部署到 Windows + 内网穿透见 docs/Win电脑部署手册.md"
