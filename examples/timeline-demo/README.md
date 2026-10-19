# 建模过程演示（timeline-demo）

用真实标杆模型 `examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json`
造一份 **5 步**修订历史，演示 `tools.timeline` 生成的「系统如何一步步建模完善」过程图。

## 文件

| 文件 | 说明 |
| --- | --- |
| `index.json` | `sysml-viz-history/v1` 历史索引（5 步，seq 0..4） |
| `step-0000-*.ir.json` … `step-0004-*.ir.json` | 每一步当时的完整 IR 快照 |
| `timeline.svg` | `export_timeline` 产物（`sysml-timeline/v1`，可直接用浏览器打开） |
| `build_demo.py` | 可重跑的生成脚本（标准库，只读 golden） |

## 这 5 步讲什么

- **第 0 步（基线，灰）**：golden 的前 6 个元素（4 条需求 + 系统/功率链 PartDefinition），已有 6 个元素；
- **第 1 步（蓝）**：+7，补齐电池、电调、电机、上下桨等部件定义；
- **第 2 步（橙）**：+7，加入 PartUsage 与第一条 Connection；
- **第 3 步（绿）**：+7，加入参数（Attribute）与上桨连接；
- **第 4 步（红）**：+7，加入约束、效率参数、动作与飞行模式状态机。

第 4 步快照与 golden IR **完全一致**（34 元素 / 20 关系）。因此图里既能看出逐级生长，
也能把最终树对回真实模型。

## 重新生成

```bash
cd sysml-modeling-agent
.venv/bin/python examples/timeline-demo/build_demo.py
```

脚本把 `generated_at` 固定为 `2026-10-19T13:00:00.000Z`，同一环境重跑 SVG 逐字节一致。
也可以直接用 CLI 重画（生成时间取当前时间）：

```bash
.venv/bin/python mcp-server/tools/timeline.py \
    --history examples/timeline-demo \
    --out examples/timeline-demo/timeline.svg
```

## 图里怎么看

- **节点颜色** = 该元素第一次出现的步骤颜色；基线元素固定灰 `#94a3b8`；
- **节点右上角徽标** = 首次出现步序号（基线为 `0`）；
- **`△N` 小标签 + 2px 描边** = 该元素在第 N 步被修改（本演示没有修改步，`tests` 里有覆盖）；
- **右侧「建模步骤」** = 每步颜色、本地时间、会话前缀、`+新增 ~修改 -删除` 统计与新增元素名；
- **底部柱图** = 每步累计元素数；第 0 步 6 → 第 4 步 34。
