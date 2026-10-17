# 标杆案例：共轴八旋翼功率链（Golden Case）

> 对应技术方案 7.3「精做一个完整的共轴八旋翼功率链 SysML 标杆模型」在 **T4 骨架**下的落地范围。
> 上位任务：9.1 的 T4 —— **需求 + 结构 + 参数；行为留空位，二期补。**

## 文件

| 文件 | 说明 |
| --- | --- |
| `golden-coaxial-power-chain.ir.json` | **事实来源**：IR JSON（`schema: sysml-ir/v1`，30 个元素、20 条关系） |
| `golden-coaxial-power-chain.sysml` | `generate_sysml` 的产物，**由生成器输出后原样存档，不得手改** |
| `README.md` | 本页 |

校验状态：`validate_model_json` → **`ok = true`，0 error，0 warning**
回验状态：`verify_sysml`（lint + 元素级比对）→ **`ok = true`**，30/30 元素匹配，0 lint error

重新生成（产物与生成器逐字节一致由 `tests/test_examples.py` 钉住）：

```bash
cd sysml-modeling-agent/mcp-server
python run_server.py --call generate_sysml --input ../examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json \
  | python -c "import json,sys; sys.stdout.write(json.load(sys.stdin)['text'])" \
  > ../examples/golden-coaxial-power-chain/golden-coaxial-power-chain.sysml
```

---

## 模型讲的是什么

一条从**任务指标**走到**参数公式**的链：

```
任务级续航（≥5.0 h，含降落裕度）
   │ decomposes
   ├── 巡航续航（≥4.0 h）          ← 本案例的主角
   │      │ refines
   │      ├── 转速比区间（0.75 ≤ eta ≤ 1.25）
   │      └── 巡航功率预算（P_cruise ≤ 0.9·P_batt_max）
   │
   └── 被满足于 ─→ 功率链：电池 → 电调 → 电机 → 桨（上/下桨各一条支路）

参数（Attribute）：
   E_batt = 1200 Wh     usableEnergyFraction = 0.8     P_cruise = 240 W
   T = E_batt × usableEnergyFraction / P_cruise = 1200 × 0.8 / 240 = 4.0 h  ← 恰好满足下限
   eta_esc = 0.95   eta_motor = 0.85   eta_prop = 0.72（共轴双桨含气动干涉）
```

**关键设计意图**：`enduranceHours = 4.0` 不是拍出来的，而是由 `batteryCapacityWh`、
`usableEnergyFraction`、`cruisePowerW` 三个参数**换算**出来的，且恰好等于
`REQ-CRUISE-ENDURANCE` 的下限 4.0 h。这样演示时的一句话就是成立的：
**「改任何一个参数，续航需求是否还满足，立刻算得出来」**——这正是方案 10.2 那条
「模型 → 参数 → 仿真 → 验证」叙事链要的效果。

---

## 元素清单（30 个）

### 需求 4 条

| id | name | 阈值字段 | satisfiedBy |
| --- | --- | --- | --- |
| `REQ-MISSION-ENDURANCE` | `MissionEndurance` | `minMissionDurationHours: 5.0`、`minLandingReserveFraction: 0.15` | `PART-POWER-CHAIN` |
| `REQ-CRUISE-ENDURANCE` | `CruiseEndurance` | `minEnduranceHours: 4.0` | `PART-BATTERY-PACK` |
| `REQ-ROTOR-SPEED-RATIO` | `RotorSpeedRatioBand` | `minSpeedRatio: 0.75`、`maxSpeedRatio: 1.25`、`maxRotorSpeedRpm: 6200.0` | `ACT-ONLINE-OPTIMIZATION` |
| `REQ-POWER-BUDGET` | `CruisePowerBudget` | `maxCruisePowerW: 260.0`、`batteryDeratingFactor: 0.9` | `PART-POWER-CHAIN` |

四条都有 `verifyMethod`，且都被 `ACT-SIM-ENDURANCE` / `ACT-ONLINE-OPTIMIZATION` 用 `verifies` 覆盖
（所以没有 `W-REQ-NO-VERIFY`）。

### 结构 7 个定义 + 8 个用法

定义：`CoaxialOctoRotorSystem`、`PowerChain`、`BatteryPack`、`ElectronicSpeedController`、
`BrushlessMotor`、`UpperRotor`、`LowerRotor`

用法（全部带 `typeRef`，`quantity` 表达数量）：`x8System`(1)、`powerChain`(1)、`batteryPack`(1)、
`escUnit`(8)、`upperMotor`(4)、`lowerMotor`(4)、`upperPropeller`(4)、`lowerPropeller`(4)

> **7 个定义全部被实例化**——所以没有 `W-PARTDEF-UNUSED`。

### 参数 9 个（`Attribute`）

`cruiseSpeed` 15 m/s · `speedRatioEta` 1.0 · `batteryCapacityWh` 1200 Wh ·
`usableEnergyFraction` 0.8 · `cruisePowerW` 240 W · `enduranceHours` 4.0 h ·
`escEfficiency` 0.95 · `motorEfficiency` 0.85 · `propellerEfficiency` 0.72

### 功能 2 个（`ActionDefinition`）

- `EnduranceSimulationRun` —— 续航仿真工况（输入 v、eta，输出 T）
- `OnlinePowerOptimization` —— 在线功率优化（输入功率遥测、空速估计，输出 v、eta）

---

## 为什么是这个范围（T4 的取舍，如实说明）

| 方案 7.3 要求的 | 本期状态 |
| --- | --- |
| 需求：任务级续航 → 巡航 ≥4h → 转速比区间 | ✅ 已覆盖（另加一条功率预算需求作为能量侧约束） |
| 结构：电池→电调→电机→桨的功率链（含上下桨） | ✅ 已覆盖，上下桨各一条支路，`connects` 逐段连接 |
| 参数：功率公式、电池容量换算 | ⚠️ **部分覆盖**：参数与换算关系齐备，但**公式以 `Attribute.description` 文本承载**——MVP 的 IR 没有正式的 `Constraint` 元素（方案 4.3 列为第 7 项，属**二期**）。没有为了放公式去自创 kind。 |
| 行为：起飞→爬升→巡航→返航→降落状态机 | ⛔ **本期留空位**（T4 明确「行为后续补」）。IR 里**刻意不含 `StateDefinition`**，`tests/test_examples.py` 把这一点钉住，避免有人误以为覆盖了。 |

**另外两处已知简化**（见 `mcp-server/schema/字段说明.md` §7）：`Attribute.unit` 与
`PartUsage.quantity` 在生成文本里以行内注释承载，`transitions` 以注释块承载——
原因是本机没有可用的官方 SysML v2 解析器来验证这些记法（`docs/T0-调研结论.md` §2），
**不发明无法验证的语法**。语义不丢：数值仍是数字、单位仍是独立字段。

---

## 这份案例的五个用途（方案 7.3）

1. **few-shot 范例** —— 给 LLM 看的「照着这样填」的完整样本（配套 `skills/element-choice` 的案例讲解）
2. **领域模板** —— 可裁剪成四旋翼变体
3. **测试基准** —— `tests/test_examples.py` 用它做端到端回归
4. **知识库镇馆** —— `knowledge/samples/` 的首份入库材料（见 `knowledge/README.md`）
5. **比赛展示物** —— 「从一句需求到模型到参数到仿真」的现场演示起点

---

## 已知待办（二期）

- [ ] 行为建模：补 `StateDefinition`（起飞 → 爬升 → 巡航（在线寻优）→ 返航 → 降落，含逆风/顺风的状态内参数漂移）
- [ ] 参数公式：等 IR 支持 `Constraint` 元素后，把 `description` 里的公式改成正式约束
- [ ] 单位与数量：拿到老师样本模型后，把注释形态改成 SysML v2 正式记法并补渲染测试
- [ ] 追溯矩阵：等 `traceability` 工具（T9）到位后，本案例应产出完整矩阵
- [ ] 参数来源核实：`1200 Wh` / `240 W` / `0.95` / `0.85` / `0.72` 等数值目前是**示例值（占位）**，
      需由团队用真实电池与桨的测试数据替换。**在替换之前，本案例的任何数值都不得作为实测结论呈现**
      （方案 10.2 的数据真实性红线）。
