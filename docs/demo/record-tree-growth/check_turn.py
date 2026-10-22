#!/usr/bin/env python3
"""录制辅助：一行输出「当前工作模型」的元素数 / 关系数 / 校验结果 / 生成文本 sha。

用法（在任意目录都行，脚本会自己找工程根）：

    sysml-modeling-agent/.venv/bin/python sysml-modeling-agent/docs/demo/record-tree-growth/check_turn.py
    ... check_turn.py --expect-elements 3 --expect-relations 3
    ... check_turn.py --expect-text-sha bb64cc2cbfdc5f5667049a76f6b57c4925a6ed29b2344c94d09d70e9ac6f6129
    ... check_turn.py --json          # 失败时打印完整 errors

输出示例：

    PASS  elements=3 relations=3 errors=0 warnings=6 text_sha=1a2b3c4d (bb64cc2c expected at end)

退出码：0 = 通过（且所有 --expect-* 都满足）；1 = 不通过。
只读：不改任何模型文件。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
DEFAULT_MODEL_REL = Path("model-output/q2-demo/q2-demo.ir.json")


def find_workspace() -> Path:
    """从脚本位置向上找同时含 `sysml-modeling-agent/` 与 `model-output/` 的目录。"""
    for parent in HERE.parents:
        if (parent / "sysml-modeling-agent").is_dir() and (parent / "model-output").is_dir():
            return parent
    return HERE.parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="录制辅助：一行校验当前工作模型")
    parser.add_argument("--model", help="模型文件路径（默认 <workspace>/model-output/q2-demo/q2-demo.ir.json）")
    parser.add_argument("--expect-elements", type=int)
    parser.add_argument("--expect-relations", type=int)
    parser.add_argument("--expect-warnings", type=int)
    parser.add_argument("--expect-text-sha", help="期望的生成文本 sha256（可只给前 8 位）")
    parser.add_argument("--compare", help="与另一份 IR 做语义相等比较（如标杆文件）")
    parser.add_argument("--json", action="store_true", help="失败时打印完整校验结果")
    args = parser.parse_args(argv)

    workspace = find_workspace()
    model_path = Path(args.model) if args.model else workspace / DEFAULT_MODEL_REL
    if not model_path.is_absolute():
        model_path = (workspace / model_path).resolve()
    if not model_path.is_file():
        print(f"FAIL  model file not found: {model_path}")
        return 1

    server_dir = workspace / "sysml-modeling-agent" / "mcp-server"
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    try:
        from tools.validator import validate_model_json  # type: ignore
        from tools.generator import generate_sysml  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  cannot import tools from {server_dir}: {exc}")
        return 1

    try:
        text = model_path.read_text(encoding="utf-8")
        model = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  JSON parse error: {exc}")
        return 1

    elements = model.get("elements") if isinstance(model, dict) else None
    if not isinstance(elements, list):
        print("FAIL  model has no `elements` array")
        return 1
    relation_count = sum(len(e.get("relations") or []) for e in elements if isinstance(e, dict))

    validation = validate_model_json(model)
    errors = validation.get("errors") or []
    warnings = validation.get("warnings") or []

    text_sha = "?"
    try:
        generated = generate_sysml(model)
        text_sha = generated.get("sha256") or "?"
    except Exception:  # noqa: BLE001 - 文本生成失败不该阻断结构校验
        text_sha = "gen-error"

    problems: list[str] = []
    if not validation.get("ok"):
        problems.append(f"errors={len(errors)}")
    if args.expect_elements is not None and len(elements) != args.expect_elements:
        problems.append(f"elements {len(elements)} != {args.expect_elements}")
    if args.expect_relations is not None and relation_count != args.expect_relations:
        problems.append(f"relations {relation_count} != {args.expect_relations}")
    if args.expect_warnings is not None and len(warnings) != args.expect_warnings:
        problems.append(f"warnings {len(warnings)} != {args.expect_warnings}")
    compare_result = None
    if args.compare:
        compare_path = Path(args.compare)
        if not compare_path.is_absolute():
            compare_path = (workspace / compare_path).resolve()
        try:
            other = json.loads(compare_path.read_text(encoding="utf-8"))
            compare_result = model == other
        except Exception as exc:  # noqa: BLE001
            compare_result = None
            problems.append(f"compare failed: {exc}")
        if compare_result is False:
            problems.append("semantic-equal=False")

    if args.expect_text_sha:
        want = args.expect_text_sha.strip().lower()
        got = str(text_sha).lower()
        if not got.startswith(want):
            problems.append(f"text_sha {got[:8]} != {want[:8]}")

    status = "PASS" if not problems else "FAIL"
    line = (
        f"{status}  elements={len(elements)} relations={relation_count} "
        f"errors={len(errors)} warnings={len(warnings)} text_sha={str(text_sha)[:8]}"
    )
    if compare_result is not None:
        line += f" compare={'equal' if compare_result else 'differs'}"
    if problems:
        line += "  |  " + "；".join(problems)
    print(line)

    if problems and args.json:
        print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
