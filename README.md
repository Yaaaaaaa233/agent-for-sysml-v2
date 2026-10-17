# sysml-modeling-agent

**给无人机比赛团队做的 SysML v2 建模智能体**：不让大模型直接写建模代码，而是让它只填一张
结构化的表（**IR JSON**），由确定性代码完成「校验 → 渲染 SysML v2 文本 → 回验」的闭环。

> 一句话：**LLM 填表，代码建模。** AI 负责理解人话，正确性由可审查、可复现的代码保证。

上位文档：《SysML 建模智能体技术方案》（`docs/SysML建模智能体技术方案.md`）。
本仓库是其中 **9.1 第一期 MVP（T0–T6）** 的交付物。

![总体架构](docs/figures/建模智能体方案_总体架构图.png)

---

## 现状（先看这个，免得误判能力边界）

| 项 | 状态 |
| --- | --- |
| IR Schema v1（6 种 kind + 5 种关系） | ✅ 完成 |
| 三个核心工具（validate / generate / query）+ 回验工具 | ✅ 完成，纯函数式 |
| MCP 服务（stdio / streamable-http + Bearer 鉴权） | ✅ 完成，契约见 §3 |
| 三份 skill（workflow / element-choice / anti-patterns） | ✅ 完成，**v1.1.0**：anti-patterns **16 条**、element-choice **9 个边界案例**（含 Cameo 案例实证条目） |
| 标杆案例（需求 + 结构 + 参数） | ✅ 完成（**行为留空位，二期补**） |
| 测试 | ✅ **186 个用例全绿**（含 40 余个应被拒绝的反例） |
| 官方 SysML v2 解析器回验 | ⛔ **未达成**——本机无 JVM，PySysML2 语法缺口不覆盖需求/属性默认值。**回验目前由内置 lint + 元素级比对承担**，如实标注，见 [T0 结论](docs/T0-调研结论.md) |
| MCP 协议链路（Streamable HTTP + Bearer 鉴权 + 4 个工具） | ✅ **已实测通过**：真实 MCP 客户端完成 `initialize` → `tools/list` → 4 次 `tools/call`，鉴权 401 行为正确。原始输出见 [EVIDENCE.txt](docs/probe-mcp-http/EVIDENCE.txt) |
| DSH 把本服务挂进 profile 并调用一次 | ✅ **已实测**（2026-10-17）：经 `cordis.patch.yml` 补丁层挂载成功，`mcp__sysml-agent__query_model` 真实调用返回正确结果。**手工写 `cordis.yml` 会被应用回写冲掉，必须走 `cordis.patch.yml`** |
| LLM 接入本身 | ⛔ 不在 MVP 范围（本期由手工构造 IR 代表其输出） |

**两条红线，请一起守住**：

1. **不得宣称「生成的文本已通过官方解析器验证」**——本期没做到。
2. **标杆案例里的数值（1200 Wh / 240 W / 0.95 / 0.85 / 0.72）是占位示例值**，
   在团队用真实测试数据替换之前，**不得当作实测结论呈现**（方案 10.2）。

---

## 1. 目录结构

```
sysml-modeling-agent/
├── skills/                                   # T3 —— 三份 skill（MD + YAML frontmatter）
│   ├── modeling-workflow/SKILL.md            #   九步 SOP（每步含输入/产出/自检）
│   ├── element-choice/SKILL.md               #   元素选型决策树 + 9 个边界案例
│   └── anti-patterns/SKILL.md                #   16 条反模式（现象/为什么错/正确做法/错误码）
├── mcp-server/                               # T1 + T2 —— 工具服务
│   ├── run_server.py                         #   启动入口（接口契约见 §3）
│   ├── requirements.txt                      #   可选依赖（一个不装也能跑）
│   ├── schema/
│   │   ├── sysml-ir-v1.json                  #   IR JSON Schema（draft 2020-12）
│   │   └── 字段说明.md                        #   字段语义 + 错误码全表
│   └── tools/
│       ├── validator.py                      #   validate_model_json
│       ├── generator.py                      #   generate_sysml
│       ├── query.py                          #   query_model
│       └── sysml_lint.py                     #   回验底座（lint + 声明抽取 + 元素级比对）
├── knowledge/                                # 知识库（本期占位 + 规划说明）
│   └── README.md
├── examples/
│   └── golden-coaxial-power-chain/           # T4 —— 标杆案例
│       ├── golden-coaxial-power-chain.ir.json
│       ├── golden-coaxial-power-chain.sysml   #   生成产物，不得手改
│       └── README.md                          #   一页说明
├── tests/                                    # T5 —— 186 个用例
│   ├── _support.py
│   ├── test_validate.py  test_generate.py  test_query.py
│   ├── test_lint_roundtrip.py  test_server.py
│   ├── test_examples.py  test_skills.py
│   ├── run_tests.sh                          #   一键运行（bash）
│   └── run_tests.bat                         #   Windows 一键运行
├── docs/
│   ├── SysML建模智能体技术方案.md              # 上位文档 —— 总体方案（架构图见 docs/figures/）
│   ├── Win电脑部署手册.md                      # 上位文档 —— Windows 部署 + 内网穿透 + 鉴权
│   ├── 本机挂载试用指引.md                     # 上位文档 —— 挂到本机 DSH 的试用步骤与回滚
│   ├── figures/
│   │   └── 建模智能体方案_总体架构图.png        #   本文顶部引用的架构图
│   ├── T0-调研结论.md                         # T0 —— DSH 规范 + 解析底座选型
│   ├── T6-演示记录.md                         # T6 —— 端到端演示（含真实输出）
│   ├── probe-pysysml2/                        #      PySysML2 实测探针与原始输出
│   ├── probe-mcp-http/                        #      MCP 协议链路探针与原始输出
│   └── demo/                                  #      T6 的全部存档产物
├── install.sh                                # 建 venv + 装依赖 + 注册 skill + 打印 MCP 配置
└── README.md
```

---

## 2. 快速开始

```bash
# ① 安装（建 venv、装可选依赖、把三份 skill 注册到 DSH 用户级 skill 目录）
cd sysml-modeling-agent
./install.sh                    # --copy 改用复制；--no-skills 不碰 DSH；--print-config 只看配置片段

# ② 冒烟测试（不需要任何第三方依赖）
python3 mcp-server/run_server.py --list-tools
python3 mcp-server/run_server.py --call validate_model_json \
    --input examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json

# ③ 跑全量测试
./tests/run_tests.sh            # Windows: tests\run_tests.bat
```

### 依赖策略（重要）

**核心逻辑全部用纯标准库实现**，因此**一个第三方依赖都不装也能完整工作**：

| 依赖 | 作用 | 缺席时 |
| --- | --- | --- |
| `fastmcp`（首选）/ `mcp`（退路） | MCP 协议外壳 | `run_server.py` 自动切到**本地调用模式**（`--list-tools` / `--call`），工具功能**完全一致**，只是不能被 DSH/扣子直接挂载 |
| `jsonschema` | 第二层 JSON Schema 交叉检查 | `schemaLayer: "unavailable"`，纯标准库规则引擎**功能不减** |

所以：**装不上依赖不停工**。这也是 Windows 部署机的保险——解析器装不上的风险已被移除。

---

## 3. 启动命令（接口契约，**部署手册按此引用，勿改动**）

```bash
python run_server.py [--transport stdio|streamable-http] [--port 8000] \
                     [--auth-token <token>] [--host 127.0.0.1]
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--transport` | `stdio` | `stdio` 本地接 DSH；`streamable-http` 供云端（扣子/Coze）接入 |
| `--port` | `8000` | 仅 `streamable-http` 生效 |
| `--auth-token` | 无 | **可选；仅 streamable-http 校验**。设置后要求请求头 `Authorization: Bearer <token>`，不匹配返回 `401` |
| `--host` | `127.0.0.1` | 仅 `streamable-http` 生效。**默认只监听本机回环**（内网穿透客户端与本体同机，够用）；如需局域网访问请显式传 `0.0.0.0` |

常用示例：

```bash
# 本地 stdio（DSH 直连）
python run_server.py

# 起 HTTP 服务（公网暴露前务必设置 --auth-token！）
python run_server.py --transport streamable-http --port 8000 --auth-token <随机长串>

# 本地调用模式（没有 MCP 依赖时的等价退路）
python run_server.py --list-tools
python run_server.py --call validate_model_json --input model.ir.json
python run_server.py --call generate_sysml       --input model.ir.json
python run_server.py --call query_model --input '{"model": {...}, "unsatisfied_requirements": true}'
python run_server.py --call verify_sysml --input '{"text": "...", "model": {...}}'
```

> 这个契约与随包的 `@deepseek-ai/dsh-mcp-client` 文档（`README.zh.md`）字段**一一对应**
> （`transport: stdio|streamable-http` + `headers.Authorization`，且 stdio 不需要鉴权），
> 来源于文档最小配置示例；**真机挂载已于 2026-10-17 实测通过**（见上文「现状」表），
> 见 [T0 结论 §1.3](docs/T0-调研结论.md)。

**这个契约不做的事（部署前须知）**：

- **只有 `--auth-token` 一种鉴权方式**，即请求头 `Authorization: Bearer <token>`。
  **没有**「把 token 塞进 URL 路径」的形态（如 `/mcp/<token>`）。
  若云端平台无法携带自定义请求头，请**在反向代理层**（Caddy / Nginx / Cloudflare 规则）解决，
  不要为此改动本契约——部署手册 §5.3 也是这么约定的。
- **没有 HTTPS**：服务只提供明文 HTTP。公网暴露必须由穿透/反代层提供 TLS。
- **`--host` 默认只绑 `127.0.0.1`**：默认只绑 127.0.0.1，不替你开 0.0.0.0
  （如需局域网暴露请显式 `--host 0.0.0.0` 并自担风险）。

---

## 4. 四个工具

| 工具名 | 职责 | 返回 |
| --- | --- | --- |
| `validate_model_json` | Schema + 语义规则校验 IR | `{ok, errors:[{code,element,message}], warnings:[...], schemaLayer}` |
| `generate_sysml` | IR → SysML v2 文本，**确定性**（同输入必得同输出；返回 `sha256` 供验证） | `{ok, text, errors, warnings, stats, sha256}` |
| `query_model` | 关键字/kind 查元素、查某 id 的引用者、查重名、列未被满足的需求 | `{ok, mode, count, results, ...}` |
| `verify_sysml` | 回验：语法自查（带行列定位）+ 声明抽取 + 与 IR 元素级比对<br>（方案 5.2 的 `parse_sysml` 的 MVP 形态，双向解析列二期） | `{ok, counts, missing, extra, mismatched, lint}` |

工具对 DSH 呈现为 `mcp__sysml-agent__<工具名>`。

**生成器会先校验再渲染**：IR 有 error 时拒绝产出文本并把错误原样返回——
目的是逼 LLM **改 JSON 而不是改文本**（方案 2.3 第 4 步）。

---

## 5. 跑测试

```bash
./tests/run_tests.sh          # 186 个用例，详细输出；追加 -q 安静模式
PYTHON=python3.12 ./tests/run_tests.sh
cd tests && python3 -m unittest discover -s . -t .    # 手工跑也可以
```

只用标准库 `unittest`，**不依赖 pytest**。当前 **186 个用例**，覆盖：

- 各类**应被拒绝**的反例（缺 `acceptanceCriteria`、`relations.target` 悬空、同 owner 重名、
  `kind` 枚举自创、数值字段写成字符串、`typeRef` 悬空……）
- **确定性**：生成的文本与 sha256 两次一致；JSON 键序变化不影响输出
- **回验**：能抓住文本里少了的 / 多出来的 / 对不上的声明，**并诚实固化它抓不到什么**
- **启动契约**：`--transport/--port/--host/--auth-token`（含 `--host` 默认 127.0.0.1）、
  Bearer 鉴权（缺头/错头/前缀不匹配都拒绝）
- **产物一致性**：仓库里存档的 `.sysml` 必须与生成器逐字节一致（防手工漂移）
- **skill 结构**：九步 SOP 齐备且每步有输入/产出/自检、决策树与边界案例数、反模式条数与必需条目
- **跨平台**：源码里不得出现硬编码的 macOS 路径

---

## 6. 标杆案例

[`examples/golden-coaxial-power-chain/`](examples/golden-coaxial-power-chain/README.md)：
一条从**任务级续航（≥5 h）→ 巡航续航（≥4 h）→ 转速比区间 [0.75, 1.25]** 的需求链，
加上**电池 → 电调 → 电机 → 桨（上下桨各一条支路）**的功率链，
以及把 `1200 Wh × 0.8 ÷ 240 W = 4.0 h` 串起来的参数换算。

`validate_model_json` → `ok=true`，**0 error 0 warning**；`verify_sysml` → 30/30 元素匹配。

**行为（StateDefinition 状态机）按 T4 约定留空位**，二期补；
参数公式目前以 `Attribute.description` 承载（正式的 `Constraint` 元素也是二期）。
这两点都由测试钉住，不会被悄悄"补上"。

---

## 7. skill 怎么注册到 DSH

T0 实机调研结论（**不是猜的**，来自 DSH 随包文档，见 [T0 §1.2](docs/T0-调研结论.md)）：

- **用户级 skill 根目录 = `$DSH_HOME/skills`**（`$DSH_HOME` 默认 `~/.dsh`）
- 格式：`<name>/SKILL.md`（目录 bundle）或 `<name>.md`（平铺文件）；
  **不支持**递归发现 `**/SKILL.md`
- YAML frontmatter **必填 `name` 与 `description`**，可选 `whenToUse` / `metadata` /
  `disable-model-invocation` / `user-invocable`
- 目录被**监视**：新增/改名/删除 skill 会在下一个模型步骤生效，**无需重启**

`./install.sh` 默认会为三份 skill 建**符号链接**（与 DSH 既有 skill 的做法一致）；
没有符号链接权限时自动改为复制，也可显式 `--copy`。

> **未确认项**：DSH 没有提供官方的「skill 一键安装」命令（`dsh --help` 与
> `dsh plugin --help` 里都没有），因此走「手工放文件」这条路。

---

## 8. 与部署手册的关系

本仓库是**被部署方**，部署步骤在 **`docs/Win电脑部署手册.md`**（由并行任务产出）。
两者的接口只有一个：本 README §3 的**启动命令契约**，手册按该契约引用：

```bash
python run_server.py --transport streamable-http --port 8000 --auth-token <token>
```

分轨说明（方案 8.2）：

| 轨道 | 怎么用本仓库 |
| --- | --- |
| **开发 / 干活轨**（DSH + 本地工具链） | `./install.sh` 注册 skill，并按 `install.sh` 打印的片段把 MCP 服务挂进 `cordis.yml`（stdio 模式） |
| **展示 / 共享轨**（扣子 / Coze） | 在 Win 电脑上以 `streamable-http` 起服务 + 内网穿透得到公网 URL，扣子侧粘贴 MCP JSON（详见部署手册） |

> 云端接入的两个已知工程风险（方案 8.5）：**MCP 服务必须公网可达**；
> **单次调用有超时上限**。因此重活儿要留在本地轨，展示前至少一周先打通链路并压测。

---

## 9. 进一步阅读

| 想了解 | 看 |
| --- | --- |
| DSH 到底查到什么、没查到什么；解析底座为什么选它 | [`docs/T0-调研结论.md`](docs/T0-调研结论.md) |
| 总体方案（上位文档） | [`docs/SysML建模智能体技术方案.md`](docs/SysML建模智能体技术方案.md) |
| Windows 部署 + 内网穿透 + 鉴权 | [`docs/Win电脑部署手册.md`](docs/Win电脑部署手册.md) |
| 挂到本机 DSH 怎么试用、怎么回滚 | [`docs/本机挂载试用指引.md`](docs/本机挂载试用指引.md) |
| 完整走一遍「加一条需求」的流程（含真实输出） | [`docs/T6-演示记录.md`](docs/T6-演示记录.md) |
| 每种 IR 字段的语义、全部错误码 | [`mcp-server/schema/字段说明.md`](mcp-server/schema/字段说明.md) |
| 建模该按什么顺序做 | [`skills/modeling-workflow/SKILL.md`](skills/modeling-workflow/SKILL.md) |
| 该用哪种元素 | [`skills/element-choice/SKILL.md`](skills/element-choice/SKILL.md) |
| 已知的坑 | [`skills/anti-patterns/SKILL.md`](skills/anti-patterns/SKILL.md) |
| 标杆案例讲的是什么 | [`examples/golden-coaxial-power-chain/README.md`](examples/golden-coaxial-power-chain/README.md) |
| 知识库怎么规划 | [`knowledge/README.md`](knowledge/README.md) |

---

## 10. 版本与二期计划

- **IR Schema 版本**：`sysml-ir/v1`。Schema 升级时必须同步升级生成器与测试集。
- **本期（T0–T6）**：一句话需求 → IR JSON → 合法 SysML v2 文本，最小闭环跑通。

二期（方案 9.2）待办，按影响排序：

1. **接入官方 SysML v2 解析器**做权威回验（先解决 JVM 部署与云端超时；接口已留薄适配层）
2. **LLM 真实接入**（DSH MCP 挂载已于 2026-10-17 实测，见上文「现状」表）
3. `parse_sysml` 双向解析（导入老师的样本模型）
4. `patch_model` 增量编辑（按 id 改子树）
5. `traceability` 追溯矩阵 / `export_simulink` 参数导出
6. IR 增补 `Constraint`（参数公式）与 `Connection` 元素 —— 预计同时要把生成器里的
   单位、数量、状态迁移三处注释改成正式语法
7. 补齐 `worked-examples` 与 `domain-patterns` 两份 skill
8. `worked-examples` 需要先拿到**老师给的 SysML v2 样本模型**做样式对齐
