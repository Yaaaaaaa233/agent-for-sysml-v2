#!/usr/bin/env python3
"""生成 ``examples/timeline-demo``：5 步真实模型历史 + 建模过程 SVG。

第 0 步取 golden 案例的前 6 个元素作基线，之后 4 步各加入 7 个元素；每一步的快照
都是当时的完整 IR，最后一步与 ``golden-coaxial-power-chain.ir.json`` 完全一致。

只使用标准库；重新生成::

    cd sysml-modeling-agent
    .venv/bin/python examples/timeline-demo/build_demo.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parents[1]
MCP_SERVER = REPO_ROOT / "mcp-server"
GOLDEN = REPO_ROOT / "examples" / "golden-coaxial-power-chain" / "golden-coaxial-power-chain.ir.json"

if str(MCP_SERVER) not in sys.path:
    sys.path.insert(0, str(MCP_SERVER))

from tools.timeline import TIMELINE_SCHEMA, export_timeline  # noqa: E402

BASELINE_COUNT = 6
GROUP_COUNT = 4
SESSION = "8e56d6b9"
AT = (
    "2026-10-19T12:40:00.000Z",
    "2026-10-19T12:44:00.000Z",
    "2026-10-19T12:47:00.000Z",
    "2026-10-19T12:50:00.000Z",
    "2026-10-19T12:52:00.000Z",
)
GENERATED_AT = "2026-10-19T13:00:00.000Z"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def semantic_projection(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """去掉属性值/描述后的语义骨架，只用于给 meta 字段一个稳定的 sha。"""
    elements = []
    for element in snapshot.get("elements", []):
        elements.append(
            {
                "id": element.get("id"),
                "kind": element.get("kind"),
                "name": element.get("name"),
                "owner": element.get("owner"),
                "relations": element.get("relations") or [],
            }
        )
    return {"package": snapshot.get("package"), "elements": elements}


def main() -> int:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    elements: List[Dict[str, Any]] = golden["elements"]
    baseline = elements[:BASELINE_COUNT]
    rest = elements[BASELINE_COUNT:]
    if len(rest) % GROUP_COUNT != 0:
        raise SystemExit("golden 剩余元素数 %d 不能被 %d 整除" % (len(rest), GROUP_COUNT))
    chunk = len(rest) // GROUP_COUNT
    groups = [rest[index * chunk : (index + 1) * chunk] for index in range(GROUP_COUNT)]

    # 清理上一轮生成的快照，避免旧文件名残留。
    for old in DEMO_DIR.glob("step-*.ir.json"):
        old.unlink()

    steps: List[Dict[str, Any]] = []
    included: List[Dict[str, Any]] = list(baseline)
    for seq in range(GROUP_COUNT + 1):
        if seq > 0:
            included = included + list(groups[seq - 1])
        included_ids = {element["id"] for element in included}
        snapshot = json.loads(json.dumps(golden))
        snapshot["elements"] = [
            element for element in elements if element["id"] in included_ids
        ]
        digest = sha256(snapshot)
        revision = digest[:8]
        snapshot_name = "step-%04d-%s.ir.json" % (seq, revision)
        snapshot_path = DEMO_DIR / snapshot_name
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        added = [] if seq == 0 else [element["id"] for element in groups[seq - 1]]
        steps.append(
            {
                "seq": seq,
                "at": AT[seq],
                "revision": revision,
                "irSha256": digest,
                "semanticSha256": sha256(semantic_projection(snapshot)),
                "elements": len(snapshot["elements"]),
                "relations": sum(
                    len(element.get("relations") or []) for element in snapshot["elements"]
                ),
                "added": added,
                "removed": [],
                "changed": [],
                "source": "baseline" if seq == 0 else "change",
                "sessionId": SESSION,
                "snapshot": snapshot_name,
            }
        )

    index = {
        "schema": "sysml-viz-history/v1",
        "workspace": str(REPO_ROOT),
        "modelPath": str(GOLDEN.relative_to(REPO_ROOT)),
        "createdAt": "2026-10-19T12:39:00.000Z",
        "updatedAt": AT[-1],
        "steps": steps,
    }
    (DEMO_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    payload = export_timeline(
        DEMO_DIR,
        DEMO_DIR / "timeline.svg",
        title="建模全过程 · CoaxialOctoRotor",
        generated_at=GENERATED_AT,
    )
    if not payload.get("ok"):
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    svg_path = Path(payload["svgPath"])
    text = svg_path.read_text(encoding="utf-8")
    summary = payload["summary"]
    print(
        "ok · %d 步 · %d 元素 · %d 关系 · %s · %.1f KB"
        % (
            summary["steps"],
            summary["elements"],
            summary["relations"],
            TIMELINE_SCHEMA,
            len(text.encode("utf-8")) / 1024.0,
        )
    )
    print("svg : %s" % svg_path)
    print("历史: %s" % (DEMO_DIR / "index.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
