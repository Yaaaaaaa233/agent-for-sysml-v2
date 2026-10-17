# Win 电脑 + 内网穿透部署手册

> **本手册的读者**：运行在这台闲置 Windows 电脑上的 DeepSeek Harness（下称 DSH）智能体。它将照本手册逐步执行部署准备工作。
>
> **本手册的写法约定**：每一步都给出①确切命令 →②预期输出形态 →③验证方法 →④失败时的下一步。凡涉及版本敏感或未经实测确认的参数，一律标注 ⚠️，**不编造**。
>
> **配套文档**：《[SysML 建模智能体技术方案](./SysML建模智能体技术方案.md)》。本手册是方案 8.5 节"公网可达"风险的落地细化。
>
> **文档版本**：v1.0（编制日期见文末修订记录）

---

## 目录

1. [目标与整体链路图](#1-目标与整体链路图)
2. [前置条件清单](#2-前置条件清单)
3. [部署 MCP 服务](#3-部署-mcp-服务)
4. [内网穿透](#4-内网穿透主方案--备选对比)
5. [鉴权与安全](#5-鉴权与安全)
6. [稳定性与开机自启](#6-稳定性与开机自启)
7. [扣子侧接入步骤](#7-扣子侧接入步骤)
8. [部署可行性实测清单（spike 验收表）](#8-部署可行性实测清单spike-验收表)
9. [故障排查 FAQ](#9-故障排查-faq)
10. [费用与决策建议](#10-费用与决策建议)

---

## 1. 目标与整体链路图

### 1.1 一句话目标

把一台**闲置 Windows 电脑**变成"服务器"：在这台电脑上跑 SysML 建模智能体的 **MCP 工具服务（Python）**，再通过**内网穿透**给它一个**公网 HTTPS URL**，让**扣子（Coze，coze.cn）云端**可以调用它。

### 1.2 整体链路图

```
┌──────────────────────────────────────────────────────────────────────┐
│  ① 扣子云端（coze.cn，公有云）                                        │
│     ┌────────────────────────────────────────────┐                   │
│     │  Agent（绑定了自定义 MCP）                  │                   │
│     │  LLM 决定调用工具 → 发起 MCP 调用            │                   │
│     └───────────────┬────────────────────────────┘                   │
└─────────────────────┼────────────────────────────────────────────────┘
                      │  HTTPS 请求（JSON-RPC over Streamable HTTP）
                      │  POST https://<公网地址>/mcp
                      │  Authorization: Bearer <token>（若扣子支持带头）
                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ② 公网（互联网）                                                     │
│     DNS 解析 <公网地址> → Cloudflare 边缘节点                          │
└─────────────────────┬────────────────────────────────────────────────┘
                      │  Cloudflare 边缘 ← 隧道（出站长连接）
                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ③ 内网穿透客户端（cloudflared.exe，跑在 Win 电脑上）                  │
│     与 Cloudflare 边缘建立 4 条出站隧道，不依赖入站端口                  │
└─────────────────────┬────────────────────────────────────────────────┘
                      │  转发到 http://localhost:8000
                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ④ Win 电脑上的 MCP Server（Python 进程）                             │
│     python run_server.py --transport streamable-http --port 8000     │
│     ┌──────────────────────────────────────────┐                     │
│     │ 7 个工具：                                │                     │
│     │  validate_model_json / generate_sysml /   │                     │
│     │  parse_sysml / query_model / patch_model /│                     │
│     │  traceability / export_simulink           │                     │
│     └──────────────────────────────────────────┘                     │
└─────────────────────┬────────────────────────────────────────────────┘
                      │  返回 JSON（工具执行结果）
                      ▼
        结果沿原路返回到扣子 Agent → LLM 组织成自然语言回复用户
```

### 1.3 为什么必须"公网可达"

这是整个方案里**唯一不能在本地闭环解决**的环节，原因两条：

1. **扣子侧只支持远程协议，不支持本地 STDIO。** 扣子官方文档《MCP》的"限制说明"原文：**"目前支持 Streamable HTTP 和 SSE 协议，暂不支持 STDIO 协议。"**（依据：<https://docs.coze.cn/mcp>）这意味着"在扣子服务器上启动子进程、用标准输入输出通信"这条路走不通——扣子云端 Agent 只能通过 **HTTP(S) URL** 连 MCP 服务。而我们的 server 跑在内网电脑上，内网地址（`192.168.x.x`、`localhost`）公网不可路由，所以**必须**用穿透把 `localhost:8000` 映射成公网 HTTPS 地址。
2. **扣子运行在公有云，物理上够不到我们的内网。** 即便同处一个校园网，扣子的云端执行环境也不在同一二层网络。穿透客户端（cloudflared）走**出站连接**主动连到 Cloudflare 边缘，因此**不需要**路由器端口映射、**不需要**公网 IP、**不需要**开放入站端口。

> **一句话结论**：MCP server 必须监听 `http://localhost:8000`，由穿透客户端把它"搬"到 `https://xxx` 公网地址上，扣子才连得上。

---

## 2. 前置条件清单

执行前逐项打勾。任何一项不满足，先补齐再往下走。

| # | 条件 | 具体要求 | 检查命令（PowerShell） | 预期输出 |
| --- | --- | --- | --- | --- |
| 1 | 操作系统 | Windows 10 或 Windows 11（64 位） | `[System.Environment]::OSVersion.Version` | 主版本 `10.0`，Build ≥ 19041 |
| 2 | Python | **3.10 及以上**（推荐 3.12） | `python --version` | `Python 3.12.x` |
| 3 | pip | 随 Python 一起安装 | `python -m pip --version` | `pip 24.x ...` |
| 4 | 管理员权限 | 能执行 `netsh`、`powercfg`、`schtasks` | 管理员 PowerShell 中 `whoami /groups \| findstr /i "S-1-5-32-544"` | 出现 `BUILTIN\Administrators` |
| 5 | 网络 | **稳定的有线网络**优先 | `ping -n 4 1.1.1.1` | 4 个包回包，丢包 0% |
| 6 | Git | 用于 clone（也可直接拷贝文件夹代替） | `git --version` | `git version 2.x.x` |
| 7 | 磁盘 | 至少 2 GB 空闲 | `Get-PSDrive C \| Select-Object Free` | Free 大于 2 GB |

### 2.1 安装 Python（两种方式，任选其一）

**方式 A：winget（推荐，Win 11 与较新 Win 10 自带 winget）**

```powershell
winget install Python.Python.3.12
```

预期输出：出现 `已成功安装` / `Successfully installed` 字样，包 ID 为 `Python.Python.3.12`。

**方式 B：官方安装包（备用路径）**：在 <https://www.python.org/downloads/windows/> 下载最新 3.12.x 的 **Windows installer (64-bit)**，运行时**务必勾选 `Add python.exe to PATH`**，再点 `Install Now`。

**验证 Python 可用（新开一个 PowerShell 让 PATH 生效，三条一起跑）：**

```powershell
python --version
python -m pip --version
python -c "import sys; print(sys.executable)"
```

预期输出形如：

```
Python 3.12.8
pip 24.3.1 from C:\Users\<用户名>\AppData\Local\Programs\Python\Python312\Lib\site-packages\pip (python 3.12)
C:\Users\<用户名>\AppData\Local\Programs\Python\Python312\python.exe
```

第三条输出的是**真实的 python.exe 绝对路径**（不是商店的 WindowsApps 桩），这是判断环境是否干净的关键。

失败时的下一步：
- `winget 不是内部或外部命令` → 系统没有 winget，改用方式 B；
- `python --version` 报"不是内部或外部命令" → 把 Python 安装目录与 `Scripts` 目录加进系统 PATH，或重装时勾选 Add to PATH；
- ⚠️ **Windows 的 `python` 别名坑**：若 `python --version` 打开了微软商店页面，说明命中了 Windows 自带的"应用执行别名"。到 `设置 → 应用 → 高级应用设置 → 应用执行别名`，关闭 `python.exe` 与 `python3.exe` 两个开关，再重开 PowerShell。

### 2.2 安装 Git（可选）

```powershell
winget install Git.Git
```

验证（新开 PowerShell）：`git --version` → 预期 `git version 2.4x.x.windows.1`。

失败时的下一步：若装不上，可跳过 Git，改用 U 盘 / 网盘 / 局域网共享**直接拷贝 `sysml-modeling-agent` 文件夹**，效果等同。

### 2.3 建一个固定的工作目录

后续所有路径都以此为准，请照抄，不要自创路径：

```powershell
New-Item -ItemType Directory -Force -Path C:\sysml-agent | Out-Null
Set-Location C:\sysml-agent
Get-Location
```

预期输出：`C:\sysml-agent`

---

## 3. 部署 MCP 服务

> 本章严格按**接口契约**执行，不自行改动仓库结构、启动参数与依赖方式。

### 3.1 契约速查（本手册全文引用口径，勿改动）

| 项 | 约定值 |
| --- | --- |
| 仓库目录 | `sysml-modeling-agent/` |
| 服务代码所在 | `sysml-modeling-agent/mcp-server/` |
| 启动入口 | `run_server.py` |
| 启动命令 | `python run_server.py --transport streamable-http --port 8000 --auth-token <token>` |
| transport 取值 | `stdio` \| `streamable-http`，**默认 stdio**；`streamable-http` 用于云端接入 |
| `--auth-token` | 可选；设置后校验请求头 `Authorization: Bearer <token>` |
| 依赖安装 | `pip install -r requirements.txt` |

> ⚠️ 上表是**接口契约**，由并行任务开发的 MVP 仓库实现。执行本手册时若发现实际仓库与该契约不一致，**以实际仓库的 README 为准，并把差异记录到第 8 章实测清单**，不要自行改代码。

### 3.2 步骤 1：获取仓库

**方式 A：git clone**

```powershell
Set-Location C:\sysml-agent
git clone <仓库地址> sysml-modeling-agent
```

把 `<仓库地址>` 换成团队实际的仓库 URL（https 或 ssh 均可）。

**方式 B：拷贝文件夹**

把团队给到的 `sysml-modeling-agent` 整个文件夹复制到 `C:\sysml-agent\` 下。

**验证：**

```powershell
Test-Path C:\sysml-agent\sysml-modeling-agent\mcp-server\run_server.py
Get-ChildItem C:\sysml-agent\sysml-modeling-agent
```

预期输出：`True`，以及仓库根目录下的文件列表。

失败时的下一步：
- 输出 `False` → `run_server.py` 不在 `mcp-server/` 下或仓库没拷全。先 `Get-ChildItem -Recurse -Filter run_server.py` 找到真实位置，再据实调整下面的 `cd` 路径；
- 报"找不到存储库" → 检查仓库 URL 与网络代理。

### 3.3 步骤 2：创建虚拟环境（venv）

```powershell
Set-Location C:\sysml-agent\sysml-modeling-agent\mcp-server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

激活成功后提示符前会出现 `(.venv)`。验证：

```powershell
Test-Path .\.venv\Scripts\python.exe
```

预期输出：`True`。

失败时的下一步：报 `无法加载文件 ... Activate.ps1，因为在此系统上禁止运行脚本`（PowerShell 执行策略所致，很常见）→ 二选一：
- 放开当前用户策略（推荐）：`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`，再重跑 `Activate.ps1`；
- 或**干脆不激活**，全程用 `.\.venv\Scripts\python.exe` 代替 `python`，效果完全一致。

> 本手册后续命令默认**已激活 venv**。未激活时请把命令里的 `python` 换成 `.\.venv\Scripts\python.exe`。

### 3.4 步骤 3：安装依赖

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

预期输出：以 `Successfully installed ...` 结尾，列出 `mcp-1.x.x fastmcp-2.x.x ...` 等包及版本。用 `pip list` 复验，确认无 `ERROR` 字样。

失败时的下一步：
- `Could not find a version that satisfies the requirement ...` → 多半是网络问题，换国内镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`；
- 包编译失败（`error: Microsoft Visual C++ 14.0 or greater is required`）→ 装 "Microsoft C++ Build Tools"，或找团队要纯 Python 依赖版本。⚠️ 这类问题**先记录再问团队**，不要硬啃。

### 3.5 步骤 4：先用 stdio 模式本地自测（关键，不要跳过）

**为什么先测 stdio**：stdio 模式不涉及端口、防火墙、隧道，是**最小变量**的验证方式。stdio 都跑不起来时加隧道只会让问题更难定位。

```powershell
python run_server.py
```

（按契约 transport 默认为 `stdio`，故不带 `--transport` 即为 stdio。也可显式写 `--transport stdio`。）

预期现象：进程**阻塞不退出**，日志打印类似"server started / listening on stdio"。stdio 模式**没有** HTTP 端口，所以**不会**有 `http://localhost:...` 输出——这是正常的。

**验证**：另开一个 PowerShell 执行——

```powershell
Get-Process python | Select-Object Id, ProcessName, Path
```

预期输出：有 `python` 进程，且 `Path` 指向 `...\mcp-server\.venv\Scripts\python.exe`（服务进程活着）。回到原窗口按 `Ctrl+C` 正常停止。

失败时的下一步：
- `ModuleNotFoundError: No module named 'xxx'` → venv 没激活或依赖没装全，回到 3.4；
- `unrecognized arguments` / `unknown option` → 实际入口参数与契约不同，用 `python run_server.py --help` 看真实参数，并把差异记入第 8 章；
- 进程瞬间退出且无报错 → 先跑 `--help`，确认入口是否要求子命令。

### 3.6 步骤 5：以 streamable-http 模式启动

先生成 token（生成方法见 5.1，此处先用占位值演示）：

```powershell
$TOKEN = "请替换为第5章生成的真实token"
python run_server.py --transport streamable-http --port 8000 --auth-token $TOKEN
```

预期现象：进程阻塞，日志出现"listening on http://127.0.0.1:8000"或"Uvicorn running on http://..."之类的行。

**验证端口在监听**（另开一个 PowerShell）：

```powershell
netstat -ano | findstr :8000
```

预期输出：至少一行 `LISTENING`：

```
TCP    127.0.0.1:8000    0.0.0.0:0    LISTENING    12345
TCP    [::1]:8000        [::]:0       LISTENING    12345
```

末列 `12345` 是 PID，可用 `Get-Process -Id 12345` 交叉核对。

失败时的下一步：`netstat` 无输出或报 `OSError: [WinError 10048]`（端口被占）→ 用 `Get-NetTCPConnection -LocalPort 8000` 查占用者，或换端口（`--port 8001`，**记得同步改第 4 章隧道命令里的端口**）。

> ⚠️ **重要认知**：服务监听 `127.0.0.1`（仅本机）**完全够用**——穿透客户端 `cloudflared` 就跑在同一台机器上，它访问 `localhost:8000` **不经过防火墙入站规则**。**不要**为了"让外网能连"把服务改成监听 `0.0.0.0` 并开放公网端口，那等于把服务直接裸奔在互联网上，风险远大于收益。

### 3.7 步骤 6：本机 curl 验证

Windows 10 1803+ 自带 `curl.exe`。先用 MCP 的 `initialize` 请求做最小连通性测试，**不带 token 应被拒（401/403）**：

```powershell
curl.exe -i -X POST http://localhost:8000/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"spike\",\"version\":\"1.0\"}}}"
```

**带上 token 应成功**（只比上一条多一行 `Authorization` 头）：

```powershell
curl.exe -i -X POST http://localhost:8000/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -H "Authorization: Bearer $TOKEN" `
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"spike\",\"version\":\"1.0\"}}}"
```

预期输出：HTTP **200 OK**，响应体是 JSON-RPC 结果，含 `"result"`，其中有 `serverInfo`（服务名与版本）与 `capabilities.tools`。若服务端返回 SSE 流，响应体形如：

```
event: message
data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"...","serverInfo":{...}}}
```

两种形态都算**通过**。失败时的下一步：

| 现象 | 原因与处理 |
| --- | --- |
| **404 Not Found** | 端点路径不对。常见是 `/mcp`，也可能是 `/messages`、`/`；查仓库 README 或看服务端日志确认 |
| **400 且提示 `Missing session ID`** | 该实现要求先 `initialize` 拿到 `Mcp-Session-Id` 响应头并在后续请求携带。属正常协议行为，扣子侧会自行处理；本地手测可先用 MCP Inspector 之类完整客户端 |
| **405 Method Not Allowed** | 端点不接受 `POST`，或端点路径不同 |
| **curl: (7) Failed to connect** | 服务没起来，回 3.6 查 `netstat` |
| **带了 token 仍 401/403** | token 传错：`$TOKEN` 未赋值，或复制时带了空格/换行 |

> ⚠️ 请求头 `Accept: application/json, text/event-stream` 是 MCP Streamable HTTP 传输的通用要求。**端点路径、是否需要 session、返回 JSON 还是 SSE，必须在 spike 中对着实际服务实测确认**，不要照抄某篇博客就当定论。

**到这一步本地链路已闭环**，记下通过日期——它是第 8 章第 ① 项的前置。

---

## 4. 内网穿透（主方案 + 备选对比）

### 4.1 主方案：Cloudflare Tunnel

选它的理由：免费、给的是**真 HTTPS 域名**、客户端主动出站不需要公网 IP、官方提供 Windows 服务化安装方式。

#### 4.1.1 安装 cloudflared

```powershell
winget install --id Cloudflare.cloudflared
```

预期输出：显示 `已找到 cloudflared` 并成功安装（包 ID 为 `Cloudflare.cloudflared`）。

验证（新开 PowerShell）：

```powershell
cloudflared --version
```

预期输出形如：`cloudflared version 2025.x.x (built ...)`。

失败时的下一步：`winget search cloudflared` 看实际包 ID；仍找不到就去官方下载页取 `cloudflared-windows-amd64.exe`，重命名为 `cloudflared.exe` 放到 `C:\sysml-agent\bin\`，用绝对路径调用。下载页：<https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/>

#### 4.1.2 第一步：快速隧道 spike（先拿到临时 URL，验证链路）

**目的**：用**最小成本**回答"扣子能不能连上我们的服务"这个最大风险问题。快速隧道不需要注册域名、不需要登录，一条命令就给出临时 `https://xxx.trycloudflare.com` 地址。

新开一个 PowerShell（**不要关掉跑 MCP server 的那个窗口**）：

```powershell
cloudflared tunnel --url http://localhost:8000
```

预期输出：终端滚动日志，最后出现一个方框：

```
+-----------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):|
|  https://random-words-here.trycloudflare.com                                            |
+-----------------------------------------------------------------------------------------+
```

**记下这个 `https://....trycloudflare.com` 地址**，它就是临时公网入口。

> ⚠️ 快速隧道的 URL 是**随机、临时**的：进程一停或电脑重启，URL 就变，**不保证可复用**。故它只用于 spike，正式演示必须换 named tunnel（4.1.3）。

**验证第 ① 项：从公网 curl 可达**（注意用 `https://xxx.trycloudflare.com/mcp`，**不是** localhost）：

```powershell
$URL = "https://random-words-here.trycloudflare.com"   # 换成你拿到的地址
curl.exe -i -X POST "$URL/mcp" `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -H "Authorization: Bearer $TOKEN" `
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"spike\",\"version\":\"1.0\"}}}"
```

预期输出：与 3.7 带 token 那次**形态一致**（200 OK + JSON 或 SSE 结果）。

**更强的验证**：用手机 4G 或另一台不在内网的电脑访问同一 URL，证明链路**真的对公网开放**，而非本机自环。

失败时的下一步：
- `502 Bad Gateway` / `Unable to reach the origin service` → cloudflared 连不上源站：查 MCP server 是否在跑、端口是否 8000；
- Cloudflare 错误页（如 1033 / 1016）→ 隧道进程已退出或 DNS 未生效，等 1–2 分钟重试或重启 cloudflared；
- 本机通、外网不通 → 出口可能做了 https 拦截或 DNS 污染，换网络重试。

#### 4.1.3 第二步：正式方案（named tunnel + 固定域名 + 开机自启）

**概要步骤**（⚠️ 细节以执行时官方文档为准）：

| 步骤 | 命令 / 动作 | 要点 |
| --- | --- | --- |
| ① 前置 | 把域名 **托管到 Cloudflare**（NS 改过去） | 需能改 NS；免费域名不行 |
| ② 登录 | `cloudflared tunnel login` | 会**弹浏览器**授权并选域名，成功后生成证书文件 |
| ③ 建隧道 | `cloudflared tunnel create sysml-mcp` | 输出含 **Tunnel ID**（UUID）与凭据 JSON 路径，记下来 |
| ④ 配 DNS | `cloudflared tunnel route dns sysml-mcp mcp.example.com` | 自动建一条 CNAME |
| ⑤ 写配置 | 建 `C:\Users\<用户名>\.cloudflared\config.yml`（见下） | ingress 指向 `http://localhost:8000` |
| ⑥ 前台试跑 | `cloudflared tunnel run sysml-mcp` | 先确认能通再装服务 |
| ⑦ 装服务 | `cloudflared service install <token>` | ⚠️ 子命令随版本变化（远程管理隧道与本地管理隧道路径不同），**以官方"Run as a service on Windows"文档为准** |
| ⑧ 设自启 | `Set-Service -Name <服务名> -StartupType Automatic` | 服务名以 `Get-Service` 查到的为准 |

`config.yml` 参考形态（字段名以官方文档为准）：

```yaml
tunnel: <Tunnel ID>
credentials-file: C:\Users\<用户名>\.cloudflared\<Tunnel ID>.json
ingress:
  - hostname: mcp.example.com
    service: http://localhost:8000
  - service: http_status:404
```

**验证：**

```powershell
cloudflared tunnel list
cloudflared tunnel info sysml-mcp
```

预期输出：列出隧道名称、ID、状态（应为 `HEALTHY` 或含活跃连接数），以及该隧道的连接信息。

失败时的下一步：`tunnel list` 为空 → 登录（②）没成功或用了不同账号；`tunnel info` 报无连接 → 隧道进程没在跑，先 `tunnel run` 前台跑起来看日志。

### 4.2 备选方案对比表

| 方案 | 免费额度 | 稳定性 | 配置难度 | 一句话评述 |
| --- | --- | --- | --- | --- |
| **Cloudflare Tunnel**（主） | 免费；快速隧道给随机 `trycloudflare.com` 域名；named tunnel 需自有域名 | 高 | 中（首次登录 + 建隧道 + 配 DNS，之后一劳永逸） | HTTPS + 可固定域名 + 可服务化自启齐全，**首选** |
| **ngrok** | 1 个固定 dev 域名、3 个在线端点、**每月 1 GB 出流量 / 2 万次请求** | 高 | **最低**（`ngrok http 8000`） | 起步最快，适合 spike；免费档有月流量上限，浏览器访问见提示页（程序调用不受影响）。<https://ngrok.com/docs/pricing-limits/free-plan-limits> |
| **花生壳（Oray）** | 有免费档，**带宽与流量受限**（常见 1 Mbps 级），需实名 | 中 | 低（图形客户端） | 国内延迟低；免费档对现场演示不够稳，付费按年买。⚠️ 额度以官网公示为准 |
| **樱花 frp** | 有免费隧道，**需实名**、隧道数个位数、常需签到换流量 | 中 | 中 | 国内延迟好；免费节点不足以承载现场演示。⚠️ 政策常变 |
| **Tailscale Funnel** | 免费档可用，**需启用 HTTPS 证书特性 + 用 MagicDNS 名称**，仅 443/8443/10000 端口 | 高 | 中偏高 | 内部访问很好；域名与端口限制**需先实测能否满足扣子要求**，不作主方案 |

> ⚠️ 上表免费额度均为编制时的认知，厂商政策变动频繁——spike 时以**各厂商官方定价页当时的表述**为准，并把结论填进第 8 章。

### 4.3 一个硬要求：必须是 HTTPS

**扣子的自定义 MCP 配置示例给的是 `https://` 地址**（官方示例：`"url": "https://docs.coze.cn/topic-api/mcp"`）。据此有两条硬约束：

1. **公网 URL 必须是 https 且证书受公共信任链认可**——Cloudflare Tunnel 与 ngrok 都自动签发受信任证书，天然满足。
2. **不要用自签证书**——它不在公共 CA 信任链内，扣子大概率因证书校验失败而拒连。若某穿透工具只能给 http 或自签 https，**直接排除**。

**验证证书受信任**（地址换成你的）：

```powershell
curl.exe -v -o NUL "https://random-words-here.trycloudflare.com/mcp" -H "Authorization: Bearer $TOKEN"
```

预期输出：TLS 握手信息含 `SSL certificate verify ok`，**没有** `certificate verify failed` / `self-signed certificate` 之类错误。⚠️ 出现证书错误就**停止**换方案，这类问题在扣子侧无法通过配置绕过。

---

## 5. 鉴权与安全

### 5.1 生成一个够强的 token

我们的服务一旦公网可达，**任何知道 URL 的人都能调用**。所以 `--auth-token` **不是可选项，是必选项**。

**生成方法（PowerShell 原生，不装任何工具）：**

```powershell
$TOKEN = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object {[char]$_})
$TOKEN
```

预期输出：一串 **48 位**随机字母数字，形如 `<48位随机字母数字串>`。

**建议**：长度 ≥ 32 位，含大小写字母与数字。**不要**用生日、手机号、`sysml2025` 这类可猜串——这是公网服务，字典攻击是真实存在的。

`TOKEN` 变量只在当前 PowerShell 会话有效，建议存到文件供脚本复用：

```powershell
New-Item -ItemType Directory -Force -Path C:\sysml-agent\secrets | Out-Null
$TOKEN | Out-File -FilePath C:\sysml-agent\secrets\mcp_token.txt -Encoding ascii -NoNewline
```

（`$TOKEN = Get-Content C:\sysml-agent\secrets\mcp_token.txt -Raw` 读回。）

> ⚠️ **安全红线**：token **不入库、不外传、不进聊天记录、不贴进任何公开文档或截图**；仓库要推 Git 就把 `secrets/` 加进 `.gitignore`；一旦怀疑泄露，**立刻生成新 token 并重启服务**。

### 5.2 Windows 防火墙：不需要放行，只做收紧

**先说结论（重要）**：Cloudflare Tunnel 与 ngrok 都是**客户端主动出站**的，它们访问本机 `127.0.0.1:8000`，**不经过防火墙入站规则**。所以：

> **本方案不需要为 8000 端口添加任何入站放行规则；正确做法是把入站收紧。**

以下加固命令需**管理员权限**的 PowerShell。

**① 确认当前没有针对 8000 的入站放行规则：**

```powershell
Get-NetFirewallRule -DisplayName "*8000*" -ErrorAction SilentlyContinue |
  Select-Object DisplayName, Direction, Action, Enabled
```

预期输出：**无输出**（没有相关规则）——这是**期望结果**。

**② 显式加一条"阻止 8000 入站"规则（可选但推荐）：**

```powershell
New-NetFirewallRule -DisplayName "Block SysML MCP 8000 Inbound" `
  -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Block
```

预期输出：打印新规则的 `Name`、`DisplayName`、`Enabled: True`、`Action: Block`。验证：

```powershell
Get-NetFirewallRule -DisplayName "Block SysML MCP 8000 Inbound" |
  Select-Object DisplayName, Direction, Action, Enabled
```

预期输出：`Direction: Inbound`、`Action: Block`、`Enabled: True`。

**③ netsh 等价写法（与 ② 二选一）：**

```cmd
netsh advfirewall firewall add rule name="Block SysML MCP 8000 Inbound" dir=in action=block protocol=TCP localport=8000
netsh advfirewall firewall show rule name="Block SysML MCP 8000 Inbound"
```

预期输出：第一条 `确定。`（`Ok.`）；第二条列出规则详情，含 `方向: 入`、`操作: 阻止`、`协议: TCP`、`本地端口: 8000`。

> ⚠️ 加规则前确认是管理员，否则报 `请求的操作需要提升`。加完**务必回到 3.7 重跑本地 curl**，确认没有误伤本机回环访问。也不建议给出站流量加白名单——Windows 默认允许全部出站，加白名单容易把系统更新与 DNS 一起掐断。

### 5.3 鉴权兜底：如果扣子无法携带 `Authorization` 头

**风险描述**：扣子的自定义 MCP 走"MCP JSON 里只给一个 `url`"的配置方式——**从官方文档示例看，配置项只有 `url` 字段，没有提供自定义请求头的入口**。这意味着我们**可能无法**让扣子带上 `Authorization: Bearer <token>`。这一点**未确认，必须实测**（第 8 章第 ⑥ 项）。

⚠️ **在 spike 之前，不要假设扣子一定能带头，也不要假设一定不能带头。**

若实测结论是"带不了头"，按以下顺序兜底（**从最推荐到最不推荐**）：

**兜底 A：把随机串做进 URL 路径（推荐，但需服务端支持）**

思路：不改协议，把秘密藏进路径，端点从 `/mcp` 改成：

```
https://<公网域名>/mcp/<random-token>
```

这样"知道 URL"就等于"持有凭证"，效果与 Bearer token 等价（前提是 HTTPS 全程加密、URL 不被日志明文记录）。

⚠️ **这需要服务端支持**，而当前接口契约**没有**这个能力（契约只有 `--auth-token` 校验 `Authorization: Bearer <token>`）。因此要么由仓库维护者加"路径前缀 token"开关，要么在**反向代理层**做（Caddy/Nginx 或 Cloudflare 侧规则改写路径）。

**本手册的处理方式**：先实测扣子能不能带头；**能带就用契约里的 `--auth-token`**；不能带，再基于 spike 结论决定是否推动服务端加路径 token——**在 spike 中验证后再定，不预先改契约**。

**兜底 B：用 Cloudflare 侧能力做准入（不改代码）**

域名托管在 Cloudflare 时，可用 **Cloudflare Access** 之类策略在边缘挡掉未授权请求。⚠️ 但 Access 通常需要**浏览器交互式登录**或额外服务令牌，扣子的 MCP 客户端**不一定**能完成交互式登录。**必须实测**，很可能行不通，仅作备选记录。

**兜底 C（不推荐）：不鉴权，靠"URL 保密"**

随机 URL + 不设 token。**强烈不推荐**：`trycloudflare.com` 之类域名可被扫描，URL 泄露即完全失守，而我们的服务会执行代码/读文件。仅在别无他法且**只用于演示当天**时考虑，演示结束立刻关停。

### 5.4 其他安全要点

| 要点 | 做法 |
| --- | --- |
| 最小暴露面 | 只穿透 **一个** 端口（8000），不要顺手把 RDP(3389)、文件共享(445) 也穿出去 |
| 不暴露真实 IP | 使用隧道方案天然隐藏家庭/宿舍公网 IP，这是相对"端口映射"的一大优势 |
| 数据边界 | 服务只处理 SysML 模型文本，**不要把含敏感信息的本地路径、密钥、论文原文喂给公网服务** |
| 日志脱敏 | 日志里**不要**打印完整 token；打印时只留前 4 位，如 `aK9m****` |
| 事后关停 | 比赛演示结束后，停掉隧道进程与服务，取消防火墙变更（如需） |

---

## 6. 稳定性与开机自启

**目标**：这台 Win 电脑要能"插上电、开机、无人干预地一直提供服务"。

### 6.1 电源计划：永不睡眠

Windows 默认会在若干分钟后休眠/关闭硬盘，那会导致服务在演示中途掉线。**必须改成永不睡眠**。

以下命令需**管理员权限**的 PowerShell / CMD。

**① 查看当前电源计划：**

```cmd
powercfg /list
```

预期输出：列出若干电源计划（GUID + 名称），其中一条带 `*`（表示当前激活）。

**② 把当前计划设为"永不睡眠、永不关屏"（交流电源下）：**

```cmd
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0
powercfg /change disk-timeout-ac 0
```

预期输出：每条命令执行后**无输出**即成功（`powercfg /change` 成功时是静默的）。

**③ 验证：**

```cmd
powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
```

预期输出：在 `当前交流电源设置索引` / `Current AC Power Setting Index` 一行看到 `0x00000000`——表示永不睡眠。

更省事的替代做法：`设置 → 系统 → 电源和电池 → 屏幕和睡眠`，把"接通电源时"的"使设备在此时间后进入睡眠状态"和"关闭屏幕"都改成 **从不**。

**④ 关系休眠（可选，但不建议完全关）：**
`powercfg /hibernate off` 会释放磁盘空间，但失去"意外断电后的快速恢复"能力。比赛前**建议保留休眠**，只关掉自动休眠。

失败时的下一步：报"参数无效" → 多半不是管理员；报 "GUID 无效" → 你的系统用了自定义电源计划，改用 `powercfg /query` 先查出 `SCHEME_CURRENT` 对应的实际 GUID。

### 6.2 开机自启：任务计划程序（schtasks）

要让**两件事**开机自动跑：MCP server 与 cloudflared 隧道。先写两个启动脚本。

`C:\sysml-agent\start_mcp.cmd`：

```bat
@echo off
cd /d C:\sysml-agent\sysml-modeling-agent\mcp-server
set /p TOKEN=<C:\sysml-agent\secrets\mcp_token.txt
"C:\sysml-agent\sysml-modeling-agent\mcp-server\.venv\Scripts\python.exe" run_server.py --transport streamable-http --port 8000 --auth-token %TOKEN% >> C:\sysml-agent\logs\mcp.log 2>&1
```

`C:\sysml-agent\start_tunnel.cmd`：

```bat
@echo off
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8000 >> C:\sysml-agent\logs\tunnel.log 2>&1
```

> ⚠️ 路径需按实际安装位置核对：cloudflared 的真实路径用 `(Get-Command cloudflared).Source` 查（winget 装常在 `C:\Program Files (x86)\cloudflared\`，但**不保证**）。正式方案（named tunnel）时第二行改为 `cloudflared.exe tunnel run sysml-mcp`，不用 `--url`。

**注册两个开机任务（管理员权限）：**

```cmd
New-Item -ItemType Directory -Force -Path C:\sysml-agent\logs | Out-Null
schtasks /create /tn "SysML-MCP-Server" /tr "C:\sysml-agent\start_mcp.cmd" /sc onstart /ru SYSTEM /rl HIGHEST /f
schtasks /create /tn "SysML-Cloudflared" /tr "C:\sysml-agent\start_tunnel.cmd" /sc onstart /ru SYSTEM /rl HIGHEST /f
```

参数含义：`/sc onstart` 开机触发；`/ru SYSTEM` 以 SYSTEM 运行（**无需用户登录**，无人值守必须这样）；`/rl HIGHEST` 最高权限；`/f` 覆盖同名任务。

预期输出：`成功: 成功创建计划任务 "SysML-MCP-Server"。`（英文系统为 `SUCCESS: The scheduled task "..." has successfully been created.`）

**验证并立刻试跑（不必重启）：**

```cmd
schtasks /query /tn "SysML-MCP-Server" /v /fo LIST
schtasks /run /tn "SysML-MCP-Server"
schtasks /run /tn "SysML-Cloudflared"
```

预期输出：查询结果里 `状态` 为 `就绪`、`以用户身份运行` 为 `SYSTEM`；`/run` 返回 `成功: 已尝试运行 "SysML-MCP-Server"。` 之后按 3.6 的 `netstat` 和 4.1.2 的公网 curl 确认真的起来了。

**图形界面等价步骤**（schtasks 报错时用）：`Win + R` → `taskschd.msc` → 右侧**创建任务**（不是"创建基本任务"）；「常规」页勾选 **不管用户是否登录都要运行** + **使用最高权限运行**；「触发器」页新建并选 **启动时**；「操作」页填 `C:\sysml-agent\start_mcp.cmd`；「设置」页勾选 **如果任务失败，按以下频率重新启动**（间隔 1 分钟、尝试 3 次）——这是断线自愈的第一道保险。

失败时的下一步：报 `拒绝访问` → 不是管理员；报 `无法启动计划任务` → 检查 `.cmd` 路径引号与脚本语法（手动双击跑一遍最直接）；"上次运行结果"非 0 → 看 `logs\` 下日志。

### 6.3 进程守护：NSSM 注册为 Windows 服务（可选）

任务计划程序够用；若想要"崩溃后自动重启 + 可用 `services.msc` 统一管理"，可以用 **NSSM** 把服务包装成 Windows 服务：

```powershell
winget install --id NSSM.NSSM
```

⚠️ winget 找不到就到官网 <https://nssm.cc/> 下 zip，取 `win64\nssm.exe` 放到 `C:\sysml-agent\bin\`。

```cmd
C:\sysml-agent\bin\nssm.exe install SysMLMCP "C:\sysml-agent\sysml-modeling-agent\mcp-server\.venv\Scripts\python.exe" "run_server.py --transport streamable-http --port 8000 --auth-token <token>"
C:\sysml-agent\bin\nssm.exe set SysMLMCP AppDirectory "C:\sysml-agent\sysml-modeling-agent\mcp-server"
C:\sysml-agent\bin\nssm.exe set SysMLMCP AppExit Default Restart
C:\sysml-agent\bin\nssm.exe set SysMLMCP Start SERVICE_AUTO_START
C:\sysml-agent\bin\nssm.exe start SysMLMCP
```

验证：`sc query SysMLMCP` → 预期 `STATE` 为 `4 RUNNING`。失败时看 `logs\mcp.err.log`，多半是 `AppDirectory` 没设导致找不到 `run_server.py`。

⚠️ 用 NSSM 时 token 会作为**命令行参数**出现在服务配置里（`services.msc` 可见）。介意的话改回 6.2 的 `.cmd` + token 文件方式。

### 6.4 日志落盘建议

| 日志 | 路径 | 内容 |
| --- | --- | --- |
| MCP server 标准输出 | `C:\sysml-agent\logs\mcp.log` | 启动、每次工具调用、错误栈 |
| MCP server 错误 | `C:\sysml-agent\logs\mcp.err.log` | 异常与堆栈 |
| 隧道日志 | `C:\sysml-agent\logs\tunnel.log` | 隧道建立/断开、边缘节点 |

查看用 `Get-Content C:\sysml-agent\logs\mcp.log -Tail 50`（换文件名即可看其他日志）。

**日志轮转**（避免写满磁盘）——`C:\sysml-agent\rotate_logs.cmd`：

```bat
@echo off
cd /d C:\sysml-agent\logs
for %%F in (mcp.log mcp.err.log tunnel.log) do (
  if exist %%F (copy /y %%F %%F.%date:~0,4%%date:~5,2%%date:~8,2% >nul & break > %%F)
)
```

⚠️ `%date%` 格式随系统区域设置而变，**这段不一定在所有机器上工作**，先手动跑一次确认，不行就改用 PowerShell 版本。注册每日任务：

```cmd
schtasks /create /tn "SysML-LogRotate" /tr "C:\sysml-agent\rotate_logs.cmd" /sc daily /st 03:00 /ru SYSTEM /rl HIGHEST /f
```

**扫异常关键字**（断线发现的直接手段）：

```powershell
Select-String -Path C:\sysml-agent\logs\tunnel.log -Pattern "error|failed|disconnect|retry" | Select-Object -Last 20
```

预期输出：正常情况下**很少或没有**匹配行。

### 6.5 断线应对：怎么发现、怎么恢复

**怎么发现断线？**

| 手段 | 做法 | 频率 |
| --- | --- | --- |
| 主动巡检脚本 | 定时 curl 公网 URL，非 200 就记一条 FAIL | 每 5 分钟 |
| 扫隧道日志 | 上面的 `Select-String` | 演示前必查 |
| 扣子侧症状 | Agent 报"工具调用失败"/MCP 显示"需重新连接" | 被动 |
| 人工确认 | 用手机 4G 打开公网 URL | 每天一次 |

**巡检脚本** `C:\sysml-agent\healthcheck.cmd`（%1=公网 URL，%2=token）：

```bat
@echo off
curl.exe -s -o NUL -w "%%{http_code}" -X POST "%1/mcp" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "Authorization: Bearer %2" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"hc\",\"version\":\"1.0\"}}}"
echo.
```

```cmd
C:\sysml-agent\healthcheck.cmd https://<你的公网地址> <token> >> C:\sysml-agent\logs\health.log 2>&1
```

预期输出：单独一行 `200`。**只要不是 200，就是断线信号。**

> ⚠️ 快速隧道（`--url`）每次重启 URL 都会变，巡检脚本里的 URL 必须手动更新——这是它不适合长期运行的又一原因，**正式方案请用 named tunnel 固定域名**。

**怎么恢复？**（按成本从低到高）

1. **隧道进程死了** → 重启 cloudflared 任务：
   ```cmd
   schtasks /end /tn "SysML-Cloudflared"
   schtasks /run /tn "SysML-Cloudflared"
   ```
2. **MCP server 死了** → 同理重启 `SysML-MCP-Server`；
3. **服务在跑但连不通** → 先 `netstat -ano | findstr :8000` 确认端口在听，再 `curl.exe` 打本机 `http://localhost:8000/mcp` 区分"本机问题"还是"隧道问题"；
4. **网络断了**（拔网线/路由重启）→ 网络恢复后**出站长连接不会自动重连某些配置**，稳妥做法是重启两个任务；
5. **电脑重启了** → 靠 6.2 的开机自启自动恢复；开机后必做一次 `netstat` + 公网 curl 双验证；
6. **兜底**：如果 5 分钟内恢复不了，**立刻切备用方案**（见第 10 章容错配置）。

---

## 7. 扣子侧接入步骤

> 依据：扣子官方文档《MCP》，<https://docs.coze.cn/mcp>

### 7.1 准备 MCP JSON

扣子的自定义 MCP 配置格式如下（**这是我们自己服务的配置**）：

```json
{
  "mcpServers": {
    "sysml-agent": {
      "url": "https://<你的公网地址>/mcp"
    }
  }
}
```

- `sysml-agent`：MCP 的显示名，可自定；
- `url`：**必须是 https**，路径按实际服务端点填（本手册按接口契约的惯例写 `/mcp`，实测以真实端点为准）。

### 7.2 在扣子侧添加

1. 打开**扣子桌面端**或**网页端**（<https://www.coze.cn>）——
   ⚠️ **官方文档明确："仅网页和桌面端支持创建自定义 MCP；移动端可以查看和使用已经添加的 MCP。"** 所以不能用手机操作这一步。
2. 从左侧导航栏进入 **扩展 > MCP**；
3. 在页面右上角单击 **添加自定义 MCP**；
4. **粘贴完整的 MCP JSON**（上面那段）；
5. 系统识别配置后，确认或修改 MCP 名称，选择 **添加到我的 MCP**；
6. 进入 **我的 > 我的 MCP**，点开这个 MCP，在 Agent 列表里单击 **添加**，把它绑定到目标 Agent。
   （也可以在 **Agent 设置**页添加，或直接在 Agent 对话里用自然语言让它安装——后者会默认绑定当前 Agent。）

### 7.3 在对话中验证

给绑定了该 MCP 的 Agent 发一条指令，例如：

```
使用 sysml-agent 工具，校验下面这段 IR JSON 是否合法：
{"elements": [ ... ]}
```

或更自然的一句话：

```
用 sysml-agent 把"给共轴八旋翼加一条需求：巡航时间不低于 4 小时"这个需求生成 SysML v2 文本
```

预期现象：
- Agent 的回复过程中出现**工具调用卡片**，显示调用的工具名（如 `validate_model_json`）与参数；
- 回复内容体现出工具返回的结果（校验通过/失败、生成的 SysML 文本）。

同时回到 Win 电脑看日志：

```powershell
Get-Content C:\sysml-agent\logs\mcp.log -Tail 30
```

预期输出：**出现一条新的调用记录**，含时间戳与工具名。这是"调用真的打到了我们机器上"的铁证。

失败时的下一步：见第 9 章 FAQ。

### 7.4 关于 MCP 数量的一个说明

扣子官方建议：**每个 Agent 最多启用 10 个 MCP**，原因是 MCP 越多、工具越多，越容易选错工具，且工具描述会占用上下文和 Token。

我们的方案在这个约束下**正合适**：**7 个工具合并为 1 个 MCP server**（`validate_model_json`、`generate_sysml`、`parse_sysml`、`query_model`、`patch_model`、`traceability`、`export_simulink`），在扣子侧只占 **1 个 MCP 名额**，还剩 9 个余量给别的用途。

### 7.5 （可选）上架团队商店供成员安装

如果希望全组同学都能一键安装：

1. 进入 **扩展 > 我的 > 我的 MCP**，找到 `sysml-agent`；
2. 单击 **···** > **上架到企业/团队 MCP 商店**；
3. 填写图标与名称，检查 MCP JSON，选择"需要成员安装时自行填写的字段"（例如把 url 留作成员自定义）；
4. 提交审核（若企业/团队未开启审核则直接上架）；
5. ⚠️ 注意：**仅 MCP 的创建者可以提交**，且**提交和上架管理仅支持 PC 端**。已上架的 MCP 删除前必须先下架；下架后已安装的成员仍可继续使用。

> ⚠️ **安全提醒**：扣子官方在"安全提示"中说明，第三方 MCP 服务的可用性、返回内容与数据处理由服务提供方负责。上架到团队商店前请确认 URL 指向的是我们自己的服务，且**不要把 token 明文写进 MCP JSON**（如已启用 `--auth-token` 且扣子支持带头，token 属于安装凭证，应通过扣子提供的凭证字段填写而非硬编码在 url 里）。

---

## 8. 部署可行性实测清单（spike 验收表）

**使用说明**：逐项执行、逐项填写。**每一项都要有证据**（命令输出、截图、日志片段）。任何一项未通过，都要在"结果"列写明失败现象与下一步动作。**本表是"部署是否可行"的唯一结论依据**——不要凭感觉判断。

| # | 验收项 | 验证方法（对应本手册章节） | 通过判据 | 结果 | 日期 | 记录人 |
| --- | --- | --- | --- | --- | --- | --- |
| ① | 穿透 URL 从公网 curl 可达 | §4.1.2：用公网 `https://xxx/mcp` 发 `initialize` | HTTP 200 + JSON/SSE 结果；再用**非本机网络**（手机 4G）复测一次 | | | |
| ② | 扣子粘贴 JSON 后连接成功 | §7.2：扩展 > MCP > 添加自定义 MCP | 扣子侧显示连接成功，MCP 出现在"我的 MCP"，无"需重新连接"提示 | | | |
| ③ | Agent 成功调用一次工具 | §7.3：对话中让它调 `validate_model_json` | 对话出现工具调用卡片；Win 电脑 `mcp.log` 出现对应记录 | | | |
| ④ | 记录单次调用延迟 | 从发指令到工具返回，掐表或看扣子侧耗时 | 记录**平均值**与**最大值**（各 ≥5 次采样） | | | |
| ⑤ | 验证超时上限 | 让某个工具 `sleep` 一个较长值，或查扣子官方文档的超时说明 | 记录**实际超时阈值**（秒）；确认 `generate_sysml`/`parse_sysml` 的实测耗时**远低于**该阈值 | | | |
| ⑥ | 鉴权方案实测（能否带 `Authorization` 头） | §5.3：先按 5.1 生成 token，服务端加 `--auth-token`，再从扣子侧调用 | 明确结论：**能带头**（则保留 `--auth-token`）或**不能带头**（则启动兜底 A/B 的评估） | | | |
| ⑦ | 断线恢复演练 | §6.5：杀掉 cloudflared 进程 → 观察现象 → 按步骤恢复 | 记录：发现断线用了多久、恢复用了多久、用了哪条恢复命令 | | | |
| ⑧ | 连续运行 24h 稳定性 | 挂机 24 小时，期间每隔 5 分钟跑 `healthcheck.cmd` | 24h 内成功率达到目标（建议 ≥99%）；统计断线次数与总断线时长 | | | |

**补充记录区**（自行增行）：

| 事项 | 现象 | 结论 | 日期 | 记录人 |
| --- | --- | --- | --- | --- |
| 实际端点路径（是否 `/mcp`） | | | | |
| 服务实际返回形态（JSON / SSE） | | | | |
| 实际安装的 cloudflared 版本与路径 | | | | |
| 实际使用的穿透方案（Cloudflare / ngrok / 其他） | | | | |
| 仓库实际接口与契约的差异 | | | | |

> **spike 的定位**：这些项目的价值在于**提前把风险消灭在演示之前**。方案文档 8.5 节的处置要求是"**展示前至少一周**打通链路并做限时压测"，本表就是那句话的逐项落地。

---

## 9. 故障排查 FAQ

### Q1. 扣子侧提示连不上 / MCP 连接失败

按此顺序排查，逐条别跳：

1. **本机通不通？** 用 3.7 带 token 的那条 `curl.exe` 打 `http://localhost:8000/mcp`。不通 → 问题在服务本身（回 §3）。
2. **隧道起来了吗？** 看 cloudflared 窗口是否还在，日志有没有 error：`Get-Content C:\sysml-agent\logs\tunnel.log -Tail 50`。
3. **公网 URL 打得通吗？** 把上条命令的 `localhost:8000` 换成公网地址：
   - `502 Bad Gateway` → 隧道活着但连不到源站，查 MCP server 与端口号；
   - 连不上/超时 → 隧道掉线或 **URL 已失效**（快速隧道重启后 URL 会变，这是头号坑）。
4. **URL 抄对了吗？** 必须是 `https://`、域名拼写正确、路径为 `/mcp`。
5. **防火墙误伤了吗？** `Get-NetFirewallRule -DisplayName "*SysML*" | Select-Object DisplayName, Direction, Action, Enabled`；若误伤先 `Disable-NetFirewallRule -DisplayName "..."` 验证。

### Q2. 扣子显示"需重新连接"

官方文档说法：**"通常是连接凭证失效，或 MCP 的服务配置、鉴权方式发生了变化。"**

1. 先确认服务端与隧道还在（Q1 步骤 1–3）；
2. 单击扣子页面的 **重新连接**——**原有 Agent 绑定关系会保留**，不必重新绑定；
3. 若我们**改过 token**，扣子侧的旧凭证必然失效，**必须**更新为新 token；
4. 若服务端加了 `--auth-token` 但扣子侧没地方填 → 正是 §8 第 ⑥ 项要实测的问题，参考 §5.3 兜底方案。

### Q3. 工具调用超时

| 成因 | 判别方法 | 对策 |
| --- | --- | --- |
| 工具本身太慢（如 `parse_sysml` 调官方解析器） | 本机单独调该工具计时 | 优化实现；重活儿留在本地轨（方案 8.5 节） |
| 网络往返慢 | 公网 curl 的 `time_total` | 换更近的穿透节点 |
| 首次调用冷启动 | 第一次慢、后续正常 | 演示前"预热"调一次 |
| 扣子侧阈值太低 | 查扣子文档 / §8 第 ⑤ 项实测 | 让工具在阈值内完成，或改异步/分步 |

计时命令（把地址换成你的）：`curl.exe -s -o NUL -w "total=%{time_total}s\n" -X POST https://<公网地址>/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -H "Authorization: Bearer $TOKEN" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"t\",\"version\":\"1\"}}}"`

预期输出形如 `total=0.187s`。本机 0.1s 而公网 3s，说明瓶颈在链路。

⚠️ **扣子的单次工具调用超时上限，官方文档未在本手册编制时确认，必须在 §8 第 ⑤ 项实测**，不要凭猜测设计工具耗时。

### Q4. 电脑重启后服务没起来

1. 任务被触发了吗？`schtasks /query /tn "SysML-MCP-Server" /v /fo LIST`（另一个任务同理），看 **上次运行时间** 与 **上次运行结果**（`0x0` 为成功）；
2. 端口在听吗？`netstat -ano | findstr :8000`；
3. 日志有话说吗？`Get-Content C:\sysml-agent\logs\mcp.err.log -Tail 50`；
4. 常见原因：任务设成了"仅在用户登录时运行"（改成 `/ru SYSTEM`）；`.cmd` 用了相对路径（脚本首行补 `cd /d <绝对路径>`）；网络未就绪任务就跑起来（触发器加 **延迟 1 分钟**）；venv 路径变了（重跑 §3.3）。

### Q5. 端口 8000 被占用

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess
```

再用 `Get-Process -Id <上一步的 OwningProcess>` 找出占用者。要么停掉它，要么给我们的服务换端口（`--port 8001`），换完**记得同步改隧道命令里的端口**。

### Q6. `pip install` 一直失败

先换国内镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`。仍失败则：检查公司/校园网代理拦截；`pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple` 后重试；报 MSVC 编译错误就装 Microsoft C++ Build Tools，或找团队换纯 Python 依赖。

### Q7. 隧道地址每次重启都变

这是**快速隧道（`cloudflared tunnel --url`）的固有行为**。彻底解决办法只有改用 **named tunnel + 自有域名**（§4.1.3）。过渡期可用下面命令从日志里捞出当前 URL：

```powershell
Get-Content C:\sysml-agent\logs\tunnel.log | Select-String -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -Last 1
```

预期输出：一行含完整临时 URL 的文本。

---

## 10. 费用与决策建议

### 10.1 全免费方案（A）vs 学生轻量云主机（B，约几十元/年）

| 维度 | 方案 A：闲置 Win 电脑 + 免费穿透 | 方案 B：学生轻量云主机 + 云上穿透/直接公网 |
| --- | --- | --- |
| **现金成本** | ≈ 0 元（穿透免费档）；named tunnel 需自有域名（域名约几十元/年） | 主机费几十元/年（学生价，随活动浮动；⚠️ 以当时活动页为准） |
| **电费** | 有（24h 开机；普通台式机一个月可能十几到几十元，取决于功耗与电价） | 无 |
| **需人值守** | 是（断电、断网、系统更新重启都要人恢复） | 否 |
| **稳定性** | 中（取决于宿舍网/家宽、Win 更新、电源） | 高（云厂商 SLA） |
| **本地仿真能力** | ✅ 能访问本地 Simulink 与官方解析器 | ❌ 碰不到本地环境 |
| **上手成本** | 低（本手册即可完成） | 中（系统、Python、进程守护、证书都要配） |
| **风险** | 演示现场断网/断电即全盘失效 | 云侧稳，但只能做纯计算类工具 |

**结论**：**两者不是二选一，而是分工**——这是方案文档 8.2 节"双轨策略"的延伸：本地轨（Win + DSH）保深度、能跑重工具；展示轨（扣子）保广度、讲得响；**Win + 穿透就是把本地轨的 MCP 工具"借"给展示轨用**。

**建议**：**先做方案 A（零成本、当天可验证）作为 spike 与备份；若 24h 稳定性实测不达标，再花钱上方案 B 作为演示主通道。**

### 10.2 比赛正式演示的容错配置（强烈建议照做）

演示当天"只有一条链路"是危险的，建议准备：

| # | 容错项 | 做法 | 为什么 |
| --- | --- | --- | --- |
| 1 | **有线网络** | 演示机与 Win 服务器都插网线，关掉 Wi-Fi 自动切换 | 无线丢包与切换是掉线主因 |
| 2 | **备用穿透** | 主用 Cloudflare Tunnel，同时备一个 ngrok 地址 | 厂商故障时 3 分钟切换 |
| 3 | **提前启动 + 预热** | 演示前 30 分钟开机、启动两个任务、调一次工具预热 | 排除冷启动与忘记启动 |
| 4 | **固定域名** | 用 named tunnel 固定域名，杜绝"URL 变了" | 快速隧道 URL 会变，是最大的坑 |
| 5 | **现场可查** | 常驻窗口显示 `mcp.log` 与 `tunnel.log` | 断线 5 秒内肉眼可见 |
| 6 | **本地直连兜底** | 演示机直接跑 DSH 本地调用同一批工具 | 穿透全挂也能演示"能建模" |
| 7 | **录屏兜底** | 提前录一段完整成功的对话流程 | 最后的安全垫 |
| 8 | **命令卡片** | 把启动/恢复命令打印贴在显示器旁 | 紧张时不用回忆命令 |
| 9 | **电源** | 全程插电并关闭睡眠，确认插座可靠 | 断电即全盘失效 |
| 10 | **关自动更新** | 演示前 3 天起暂停 Windows 自动更新 | 系统偷偷重启一次演示就废了 |

### 10.3 一句话决策建议

> **花一个下午把方案 A 打通并跑满 24h 稳定性测试**；8 项 spike 全绿就用它上台；**任何一项转黄或转红，就在正式演示前花钱上方案 B 作主链路**，方案 A 降级为备份。这笔几十元，买的是"演示当天不翻车"的保险费。

---

## 附：修订记录

| 版本 | 日期 | 修订人 | 说明 |
| --- | --- | --- | --- |
| v1.0 | ⚠️ 待填 | ⚠️ 待填 | 初版：Win 电脑 + 内网穿透部署手册（10 章 + spike 验收表 + FAQ） |

## 附：参考链接

- 扣子官方文档《MCP》（限制说明、添加自定义 MCP、上架商店）：<https://docs.coze.cn/mcp>
- 扣子开放平台：<https://www.coze.cn>
- Cloudflare Tunnel 官方文档（下载、Windows 服务化）：<https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/>
- ngrok 免费档限制：<https://ngrok.com/docs/pricing-limits/free-plan-limits>
- Python 官方 Windows 下载：<https://www.python.org/downloads/windows/>
- NSSM：<https://nssm.cc/>
- 配套方案文档：《[SysML 建模智能体技术方案](./SysML建模智能体技术方案.md)》

> ⚠️ **最后提醒**：本手册中所有形如"具体子命令随版本变化""需实测确认"的标注，都是**已知的不确定性**，不是疏忽。执行者请在 spike 阶段优先验证这些点，并把结论回填到第 8 章的表格里——**手册的完成度，最终由那张表决定。**
