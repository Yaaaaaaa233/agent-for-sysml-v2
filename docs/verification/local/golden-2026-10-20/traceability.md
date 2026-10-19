# 追溯矩阵

> 模型：`CoaxialOctoRotor`；需求 4 条；状态分布：satisfied-and-verified 4 / satisfied 0 / verified-only 0 / unsatisfied 0。

| 需求 id | 名称 | 需求摘要 | satisfiedBy | verifiedBy | 状态 |
| --- | --- | --- | --- | --- | --- |
| `REQ-CRUISE-ENDURANCE` | CruiseEndurance | 巡航时间不低于 4 小时 | `PART-BATTERY-PACK` | `ACT-SIM-ENDURANCE` | satisfied-and-verified |
| `REQ-MISSION-ENDURANCE` | MissionEndurance | 任务级续航：共轴八旋翼须按指定任务剖面完成起飞、巡航与安全返航。 | `PART-POWER-CHAIN` | `ACT-SIM-ENDURANCE` | satisfied-and-verified |
| `REQ-POWER-BUDGET` | CruisePowerBudget | 巡航稳态下整机电功率不超过电池可持续放电功率上限。 | `PART-POWER-CHAIN` | `ACT-SIM-ENDURANCE` | satisfied-and-verified |
| `REQ-ROTOR-SPEED-RATIO` | RotorSpeedRatioBand | 在线寻优给出的上下桨转速比 eta 必须落在允许工作区间内。 | `ACT-ONLINE-OPTIMIZATION` | `ACT-ONLINE-OPTIMIZATION` | satisfied-and-verified |

## 缺口

- 未满足（无 satisfiedBy）：—
- 未被验证的需求：—
- 未被验证的功能（ActionDefinition 无 verifies）：—
