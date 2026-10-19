"""模型本地验证驱动（L0 结构校验 → L1 生成/回验（含官方解析器）→ L2 追溯检查）。

这是**验证脚本**，不是产品代码：它只按顺序调用 ``mcp-server/run_server.py`` 里与
MCP 传输完全相同的 ``call_*`` 函数，把每一步的原始输出落盘成证据，供人工复核。
不新增任何校验规则，也不改写任何工具结果。

用法（必须用仓库自己的虚拟环境，原因见 README §"为什么是 .venv/bin/python"）::

    cd sysml-modeling-agent
    .venv/bin/python docs/verification/local/verify_model.py \
        examples/golden-coaxial-power-chain/golden-coaxial-power-chain.ir.json \
        docs/verification/local/golden-2026-10-20

    # 跳过官方解析器（没装 JRE / 只想跑得快）
    .venv/bin/python docs/verification/local/verify_model.py <model.ir.json> <outdir> --no-official

产出（全部落在 <outdir>）::

    01-validate.json     validate_model_json 原始输出
    02-generate.json     generate_sysml 原始输出（去掉 text，避免与 model.sysml 重复）
    model.sysml          生成文本（与 02 同一次调用；可直接给 MSOSA 导入）
    03-verify.json       verify_sysml(official=True) 原始输出
    04-traceability.json traceability 原始输出（json）
    traceability.md      追溯矩阵（markdown）
    report.json          汇总（各层耗时/结果/输入 sha256）

退出码：全部通过（L0 errors=0 且 官方解析器无诊断且 元素级比对无缺口）为 0，
否则为 1；warning 与追溯缺口只记录、不阻断。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "mcp-server"))

import run_server as R  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="模型本地验证（L0/L1/L2）")
    ap.add_argument("model", help="IR JSON 路径（schema=sysml-ir/v1）")
    ap.add_argument("outdir", help="证据输出目录（不存在会创建）")
    ap.add_argument("--no-official", action="store_true", help="跳过官方 Pilot Implementation 解析")
    args = ap.parse_args()

    src = Path(args.model).resolve()
    out = Path(args.outdir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    raw = src.read_bytes()
    ir = json.loads(raw)
    relations = sum(len(e.get("relations") or []) for e in ir["elements"])
    report = {
        "schema": "sysml-verify-report/v1",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": {
            "path": str(src),
            "irSha256": hashlib.sha256(raw).hexdigest(),
            "elements": len(ir["elements"]),
            "relations": relations,
            "package": ir.get("package"),
            "schema": ir.get("schema"),
        },
        "python": sys.executable,
        "layers": {},
        "verdict": {},
    }

    # ---- L0：IR 结构与语义规则（validator 内置引擎 + 可选 JSON Schema 第二层）----
    t = time.time()
    v = R.call_validate_model_json(ir)
    report["layers"]["L0_validate"] = {
        "seconds": round(time.time() - t, 3),
        "ok": bool(v.get("ok")),
        "errors": v.get("errors", []),
        "warnings": v.get("warnings", []),
        "schemaLayer": v.get("schemaLayer"),
    }
    (out / "01-validate.json").write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- L1a：IR → SysML v2 文本（确定性渲染）----
    t = time.time()
    g = R.call_generate_sysml(ir)
    text = g.get("text", "")
    g2 = R.call_generate_sysml(ir)
    (out / "model.sysml").write_text(text, encoding="utf-8")
    report["layers"]["L1_generate"] = {
        "seconds": round(time.time() - t, 3),
        "ok": bool(g.get("ok")),
        "sha256": g.get("sha256"),
        "chars": len(text),
        "lines": text.count("\n") + 1 if text else 0,
        "deterministic": g2.get("sha256") == g.get("sha256"),
        "stats": g.get("stats"),
    }
    (out / "02-generate.json").write_text(
        json.dumps({k: g.get(k) for k in ("ok", "errors", "warnings", "stats", "sha256")},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ---- L1b：文本回验（内置 lint + 元素级比对 + 可选官方解析器）----
    official = not args.no_official
    t = time.time()
    vf = R.call_verify_sysml(text, ir, official=official)
    report["layers"]["L1_verify"] = {
        "seconds": round(time.time() - t, 3),
        "officialRequested": official,
        "ok": bool(vf.get("ok")),
        "counts": vf.get("counts"),
        "missing": vf.get("missing"),
        "extra": vf.get("extra"),
        "mismatched": vf.get("mismatched"),
        "official": (
            {k: (vf.get("official") or {}).get(k) for k in ("status", "ok", "backend", "diagnostics", "detail")}
            if official else None
        ),
    }
    (out / "03-verify.json").write_text(json.dumps(vf, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- L2：追溯检查（未满足需求 / 未验证需求与功能）----
    t = time.time()
    tr = R.call_traceability(ir, fmt="md")
    (out / "04-traceability.json").write_text(json.dumps(tr, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "traceability.md").write_text(tr.get("content", ""), encoding="utf-8")
    report["layers"]["L2_traceability"] = {
        "seconds": round(time.time() - t, 3),
        "ok": bool(tr.get("ok")),
        "gaps": tr.get("gaps"),
        "matrixRows": len(tr.get("matrix") or []),
    }

    # ---- 判定（只按可复算事实，不按"看起来还行"）----
    l0 = report["layers"]["L0_validate"]
    l1 = report["layers"]["L1_verify"]
    off = l1.get("official") or {}
    official_ok = (not official) or (off.get("status") == "available" and off.get("ok") is True)
    report["verdict"] = {
        "pass": bool(l0["ok"] and not l0["errors"] and official_ok
                     and not l1["missing"] and not l1["extra"] and not l1["mismatched"]),
        "warnings": len(l0["warnings"]),
        "officialPass": official_ok,
        "traceabilityGaps": sum(len(x) for x in (report["layers"]["L2_traceability"]["gaps"] or {}).values()),
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report["verdict"], ensure_ascii=False))
    print(f"证据已写入: {out}")
    return 0 if report["verdict"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
