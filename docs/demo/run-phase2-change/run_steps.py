#!/usr/bin/env python3
"""二期演示：对标杆案例做一次需求变更，看追溯矩阵能否自动反映影响范围。

用法（在仓库根执行）：

    PYTHONPATH="$PWD/mcp-server" .venv/bin/python docs/demo/run-phase2-change/run_steps.py

本脚本只调用仓库里**已实现的工具函数**（与 MCP 工具同一批代码路径），把每一步的
真实返回写进同目录的 step*.txt。没有手写任何工具输出。

产物：
    step1-import.txt                  parse_sysml 导入
    step1-imported.ir.json            导入得到的 IR（后续补丁的输入）
    step2-trace-before.txt            traceability 基线（含 gaps）
    step3-patch.txt                   patch_model 需求变更 + diff
    step3-patched.ir.json             变更后的 IR
    step4-validate-generate-verify.txt  validate / generate / verify(official)
    step4-changed.sysml               变更后的生成文本
    step5-trace-after.txt             traceability 变更后 + focus 影响面
    step6-export.txt                  export_simulink（阈值应体现 5.0）

所有数值均为占位值，本演示不含任何实测数据。
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO / "mcp-server") not in sys.path:
    sys.path.insert(0, str(REPO / "mcp-server"))

from tools.export import export_simulink  # noqa: E402
from tools.generator import generate_sysml  # noqa: E402
from tools.official_parser import parse_with_official  # noqa: E402
from tools.parser import parse_sysml  # noqa: E402
from tools.patch import patch_model  # noqa: E402
from tools.sysml_lint import roundtrip_check  # noqa: E402
from tools.trace import traceability  # noqa: E402
from tools.validator import load_model, validate_model_json  # noqa: E402

GOLDEN_IR = REPO / "examples" / "golden-coaxial-power-chain" / "golden-coaxial-power-chain.ir.json"
GOLDEN_SYSML = (
    REPO / "examples" / "golden-coaxial-power-chain" / "golden-coaxial-power-chain.sysml"
)

#: 变更目标：巡航续航下限 4.0 h → 5.0 h（占位变更，不代表任何实测结论）
NEW_MIN_ENDURANCE_HOURS = 5.0


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def write(name: str, blocks: List[str]) -> None:
    """写 step 文件。

    工具输出里的仓库绝对路径统一替换为 `<repo>`（纯机械替换，其余字符原样保留），
    目的是让本目录的产物换机器也能读——与 `docs/probe-official-parser/EVIDENCE.txt`
    「省略绝对路径前缀」的口径一致。替换动作在 RUN.md 里明写，不隐藏。
    """
    text = "\n".join(blocks).replace(str(REPO), "<repo>") + "\n"
    (HERE / name).write_text(text, encoding="utf-8")
    print("[ok] %s" % name)


def element(model: Dict[str, Any], element_id: str) -> Dict[str, Any]:
    for item in model["elements"]:
        if item.get("id") == element_id:
            return item
    raise KeyError(element_id)


def replace_element(model: Dict[str, Any], new_element: Dict[str, Any]) -> None:
    for index, item in enumerate(model["elements"]):
        if item.get("id") == new_element["id"]:
            model["elements"][index] = new_element
            return
    raise KeyError(new_element["id"])


# --------------------------------------------------------------------------------------
# 第 1 步：导入（parse_sysml：文本 → IR）
# --------------------------------------------------------------------------------------
def step1() -> Dict[str, Any]:
    text = GOLDEN_SYSML.read_text(encoding="utf-8")
    result = parse_sysml(text)
    model = result.get("model")

    blocks = [
        "# 第 1 步：parse_sysml 导入重新生成的 golden .sysml → IR",
        "#",
        "# 等价命令行（仓库根执行）：",
        '#   PYTHONPATH="$PWD/mcp-server" .venv/bin/python -m tools.parser \\',
        "#     examples/golden-coaxial-power-chain/golden-coaxial-power-chain.sysml",
        "#",
        "# 本文件由 docs/demo/run-phase2-change/run_steps.py 实际执行后写出，未手工编辑。",
        "",
        "输入：examples/golden-coaxial-power-chain/golden-coaxial-power-chain.sysml",
        "      chars  = %d" % len(text),
        "      sha256 = %s" % sha256_text(text),
        "",
        "返回（原样）：",
        dump({key: result.get(key) for key in ("ok", "errors", "warnings", "unsupported", "stats")}),
        "",
    ]

    if result.get("ok") and isinstance(model, dict):
        (HERE / "step1-imported.ir.json").write_text(
            json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("[ok] step1-imported.ir.json")
        golden = load_model(GOLDEN_IR)

        def normalized(m: Dict[str, Any]) -> List[Dict[str, Any]]:
            items = []
            for item in m["elements"]:
                clone = {k: v for k, v in item.items() if k != "relations"}
                clone["relations"] = sorted(
                    (item.get("relations") or []),
                    key=lambda r: (r.get("type", ""), r.get("target", "")),
                )
                items.append(clone)
            return sorted(items, key=lambda e: e["id"])

        same = normalized(model) == normalized(golden)
        blocks += [
            "导入结果与仓库里的 golden IR 做元素级比对（id/kind/name/owner/properties/relations）：",
            "  元素数 = %d，关系数 = %d" % (
                len(model["elements"]),
                sum(len(e.get("relations") or []) for e in model["elements"]),
            ),
            "  与 golden IR 元素级等价：%s" % ("是 ✅" if same else "否 ⛔"),
            "",
            "落盘：step1-imported.ir.json（sha256 %s）"
            % sha256_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n"),
        ]
        if not same:
            raise SystemExit("step1 导入结果与 golden IR 不等价，演示中止")
    else:
        blocks.append("⛔ 导入失败：%s" % dump(result.get("errors")))
        write("step1-import.txt", blocks)
        raise SystemExit("step1 导入失败")

    write("step1-import.txt", blocks)
    return model


# --------------------------------------------------------------------------------------
# 第 2 步：基线追溯矩阵
# --------------------------------------------------------------------------------------
def step2(model: Dict[str, Any]) -> Dict[str, Any]:
    result = traceability(model, fmt="md")
    blocks = [
        "# 第 2 步：traceability 基线（变更前）",
        "#",
        "# 等价命令行：",
        '#   PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call traceability \\',
        '#     --model-file docs/demo/run-phase2-change/step1-imported.ir.json --input \'{"fmt": "md"}\'',
        "",
        "ok = %s  errors = %s" % (result["ok"], result["errors"]),
        "matrix（%d 行）与 gaps 原样：" % len(result.get("matrix") or []),
        dump({"matrix": result["matrix"], "gaps": result["gaps"]}),
        "",
        "===== content（fmt=md）=====",
        result["content"] or "(None)",
        "",
    ]
    write("step2-trace-before.txt", blocks)
    return result


# --------------------------------------------------------------------------------------
# 第 3 步：patch_model 做一次需求变更
# --------------------------------------------------------------------------------------
def build_ops(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    requirement = copy.deepcopy(element(model, "REQ-CRUISE-ENDURANCE"))
    requirement["properties"]["text"] = "巡航时间不低于 5 小时"
    requirement["properties"]["acceptanceCriteria"] = (
        "在巡航速度 v 与转速比 eta 的稳态工作点下，满电续航时间 T >= 5.0 h"
    )
    requirement["properties"]["minEnduranceHours"] = NEW_MIN_ENDURANCE_HOURS

    endurance = copy.deepcopy(element(model, "ATTR-ENDURANCE"))
    endurance["properties"]["description"] = (
        "续航换算：T = E_batt * usableEnergyFraction / P_cruise。代入 1200 Wh、0.8、240 W "
        "得 T = 4.0 h；需求下限已由 4.0 h 改为 5.0 h（占位变更），当前设计不再满足该下限，"
        "缺口由 traceability 暴露。"
    )

    constraint = copy.deepcopy(element(model, "CONSTRAINT-ENDURANCE-BUDGET"))
    constraint["properties"]["description"] = (
        "续航换算约束：电池可用能量除以巡航功率得到续航时间。parameters 把公式里的符号"
        "绑定到 Attribute 元素；1200 Wh / 0.8 / 240 W、换算结果 4.0 h 与需求下限 5.0 h "
        "均为占位示例值，非实测结论。"
    )

    return [
        {"op": "update_element", "id": "REQ-CRUISE-ENDURANCE", "element": requirement},
        {"op": "update_element", "id": "ATTR-ENDURANCE", "element": endurance},
        {"op": "update_element", "id": "CONSTRAINT-ENDURANCE-BUDGET", "element": constraint},
    ]


def step3(model: Dict[str, Any]) -> Dict[str, Any]:
    ops = build_ops(model)
    (HERE / "step3-ops.json").write_text(
        json.dumps(ops, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("[ok] step3-ops.json")
    result = patch_model(model, ops, validate=True)

    blocks = [
        "# 第 3 步：patch_model 做一次需求变更（3 个 update_element，原子应用）",
        "#",
        "# 变更内容：REQ-CRUISE-ENDURANCE 的 minEnduranceHours 4.0 → 5.0（占位变更），",
        "# 同步所有「提到 4.0 h」的字段（需求正文 / 验收判据 / 参数描述 / 约束描述）。",
        "#",
        "# 等价命令行：",
        '#   PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call patch_model \\',
        '#     --model-file docs/demo/run-phase2-change/step1-imported.ir.json \\',
        '#     --input "{\\"ops\\": $(cat docs/demo/run-phase2-change/step3-ops.json)}"',
        "",
        "===== ops（实际传入）=====",
        dump(ops),
        "",
        "===== 返回 =====",
        "ok      = %s" % result["ok"],
        "errors  = %s" % dump(result.get("errors")),
        "warnings= %s" % dump(result.get("warnings")),
        "",
        "diff（%d 条）：" % len(result.get("diff") or []),
        dump(result.get("diff")),
        "",
    ]

    if result["ok"] and isinstance(result.get("model"), dict):
        patched = result["model"]
        (HERE / "step3-patched.ir.json").write_text(
            json.dumps(patched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("[ok] step3-patched.ir.json")
        blocks += [
            "落盘：step3-patched.ir.json（sha256 %s）"
            % sha256_text(json.dumps(patched, ensure_ascii=False, indent=2) + "\n"),
            "变更后元素数 = %d，关系数 = %d（与变更前一致，补丁只改字段）"
            % (
                len(patched["elements"]),
                sum(len(e.get("relations") or []) for e in patched["elements"]),
            ),
            "",
            "变更后 REQ-CRUISE-ENDURANCE：",
            dump(element(patched, "REQ-CRUISE-ENDURANCE")["properties"]),
        ]
        write("step3-patch.txt", blocks)
        return patched

    write("step3-patch.txt", blocks)
    raise SystemExit("step3 patch 失败")


# --------------------------------------------------------------------------------------
# 第 4 步：校验 / 生成 / 回验（含官方解析器）
# --------------------------------------------------------------------------------------
def step4(model: Dict[str, Any]) -> str:
    validation = validate_model_json(model)
    generated = generate_sysml(model)
    text = generated.get("text", "")
    (HERE / "step4-changed.sysml").write_text(text, encoding="utf-8")
    print("[ok] step4-changed.sysml")

    roundtrip = roundtrip_check(model, text)
    official = parse_with_official(text)
    verify = dict(roundtrip)
    verify["official"] = official
    if official.get("status") != "available" or official.get("ok") is not True:
        verify["ok"] = False

    blocks = [
        "# 第 4 步：变更后 validate → generate → verify（含 official）",
        "#",
        "# 等价命令行：",
        '#   PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call validate_model_json \\',
        '#     --model-file docs/demo/run-phase2-change/step3-patched.ir.json',
        '#   PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call generate_sysml \\',
        '#     --model-file docs/demo/run-phase2-change/step3-patched.ir.json',
        '#   PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call verify_sysml \\',
        '#     --text "$(cat docs/demo/run-phase2-change/step4-changed.sysml)" \\',
        '#     --model-file docs/demo/run-phase2-change/step3-patched.ir.json \\',
        '#     --input \'{"official": true}\'',
        "",
        "===== validate_model_json =====",
        dump({key: validation.get(key) for key in ("ok", "errors", "warnings", "schemaLayer")}),
        "",
        "===== generate_sysml =====",
        "ok      = %s" % generated["ok"],
        "sha256  = %s" % generated.get("sha256"),
        "stats   = %s" % dump(generated.get("stats")),
        "（文本已落盘为 step4-changed.sysml，chars=%d，sha256=%s）"
        % (len(text), sha256_text(text)),
        "",
        "===== verify_sysml（内置 lint + 元素级比对）=====",
        dump(
            {
                "ok": roundtrip["ok"],
                "counts": roundtrip.get("counts"),
                "missing": roundtrip.get("missing"),
                "extra": roundtrip.get("extra"),
                "mismatched": roundtrip.get("mismatched"),
            }
        ),
        "",
        "===== verify_sysml(official=true) 的 official 键 =====",
        dump(
            {
                "ok": verify["ok"],
                "official": {
                    "ok": official.get("ok"),
                    "backend": official.get("backend"),
                    "status": official.get("status"),
                    "diagnostics": official.get("diagnostics"),
                    "detail": official.get("detail"),
                },
            }
        ),
        "",
        "口径：上面 official 只说明「语法与引用解析」被官方 Pilot Implementation 接受，",
        "语义/建模质量未验证；内置 lint + 元素级比对与官方结果分别标注，互不冒充。",
        "",
    ]
    write("step4-validate-generate-verify.txt", blocks)
    return text


# --------------------------------------------------------------------------------------
# 第 5 步：变更后追溯矩阵 + 影响面
# --------------------------------------------------------------------------------------
def step5(model: Dict[str, Any], before: Dict[str, Any], changed_ids: List[str]) -> None:
    after = traceability(model, fmt="md")
    focus_result = traceability(model, focus="REQ-CRUISE-ENDURANCE", fmt="md")
    changed_focus = traceability(model, focus=changed_ids, fmt="json")

    before_rows = {row["requirement"]: row for row in before["matrix"]}
    diff_rows = []
    for row in after["matrix"]:
        old = before_rows.get(row["requirement"], {})
        if old != row:
            diff_rows.append(
                {
                    "requirement": row["requirement"],
                    "before": {
                        "text_short": old.get("text_short"),
                        "status": old.get("status"),
                    },
                    "after": {
                        "text_short": row.get("text_short"),
                        "status": row.get("status"),
                    },
                }
            )

    blocks = [
        "# 第 5 步：变更后 traceability（矩阵 + 缺口 + 影响面）",
        "#",
        "# 等价命令行：",
        '#   PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call traceability \\',
        '#     --model-file docs/demo/run-phase2-change/step3-patched.ir.json --input \'{"fmt": "md"}\'',
        '#   PYTHONPATH="$PWD/mcp-server" .venv/bin/python mcp-server/run_server.py --call traceability \\',
        '#     --model-file docs/demo/run-phase2-change/step3-patched.ir.json \\',
        '#     --input \'{"focus": "REQ-CRUISE-ENDURANCE", "fmt": "md"}\'',
        "",
        "===== 5.1 矩阵自动反映了什么（变更前 vs 变更后逐行比对）=====",
        "矩阵有变化的行：%d 行（其余 %d 行逐字段相同）"
        % (len(diff_rows), len(after["matrix"]) - len(diff_rows)),
        dump(diff_rows),
        "",
        "说明：矩阵的 status 由 satisfiedBy / verifiedBy 结构决定，本次变更只改字段值与",
        "文本，不改结构，所以 status 不变、text_short 从 4 小时变成 5 小时——矩阵确实跟着",
        "事实来源（IR）自动重算，不需要手工维护表格。",
        "",
        "===== 5.2 变更后 gaps =====",
        dump(after["gaps"]),
        "",
        "===== 5.3 traceability(focus=\"REQ-CRUISE-ENDURANCE\") 的影响面 =====",
        "impact =",
        dump(focus_result["impact"]),
        "",
        "===== 5.4 以「被改的 3 个元素」为焦点的合并影响面 =====",
        "focus = %s" % dump(changed_ids),
        "impact =",
        dump(changed_focus["impact"]),
        "",
        "===== 5.5 content（fmt=md，focus=REQ-CRUISE-ENDURANCE）=====",
        focus_result["content"] or "(None)",
        "",
    ]
    write("step5-trace-after.txt", blocks)


# --------------------------------------------------------------------------------------
# 第 6 步：导出参数表（阈值应为 5.0）
# --------------------------------------------------------------------------------------
def step6(model: Dict[str, Any]) -> None:
    md = export_simulink(model, fmt="md", scope="all")
    csv = export_simulink(model, fmt="csv", scope="all")
    rows = md.get("rows") or []
    threshold_rows = [
        row
        for row in rows
        if row.get("kind") == "RequirementThreshold"
        and row.get("id") == "REQ-CRUISE-ENDURANCE"
    ]

    csv_lines = csv.get("content", "").splitlines()
    endurance_csv = [line for line in csv_lines if "minEnduranceHours" in line]

    blocks = [
        "# 第 6 步：export_simulink（变更后参数表）",
        "#",
        "# 等价命令行：",
        '#   PYTHONPATH="$PWD/mcp-server" .venv/bin/python -m tools.export \\',
        "#     docs/demo/run-phase2-change/step3-patched.ir.json --fmt md --scope all",
        "",
        "ok = %s  rows = %d  notes = %d" % (md["ok"], len(rows), len(md.get("notes") or [])),
        "errors = %s" % dump(md.get("errors")),
        "",
        "===== 6.1 巡航续航阈值行（应体现 5.0）=====",
        dump(threshold_rows),
        "",
        "===== 6.2 CSV 里的同一行 =====",
    ]
    blocks += endurance_csv or ["(未找到 minEnduranceHours 行)"]
    blocks += [
        "",
        "===== 6.3 Markdown 参数表（fmt=md, scope=all）=====",
        md["content"],
        "",
        "===== 6.4 notes =====",
        dump(md.get("notes")),
        "",
        "⚠️ 表中数值全部是占位值（1200 Wh / 240 W / 0.95 / 0.85 / 0.72 / 5.0 h），",
        "不是实测结论；export_simulink 只把 IR 里的 defaultValue 透传出来，不判断物理合理性。",
        "",
    ]
    write("step6-export.txt", blocks)


def main() -> int:
    imported = step1()
    before = step2(imported)
    patched = step3(imported)
    step4(patched)
    changed_ids = ["REQ-CRUISE-ENDURANCE", "ATTR-ENDURANCE", "CONSTRAINT-ENDURANCE-BUDGET"]
    step5(patched, before, changed_ids)
    step6(patched)
    print("\n全部步骤完成：6 个 step 文件 + 3 个 IR/文本产物。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
