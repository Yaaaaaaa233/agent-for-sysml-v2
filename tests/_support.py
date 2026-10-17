"""测试公共支撑：把 ``mcp-server`` 挂进 ``sys.path``，并提供基准模型与断言助手。

不依赖 pytest；只用标准库 ``unittest``。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

#: 仓库根（tests/ 的上一级）
REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_SERVER = REPO_ROOT / "mcp-server"
EXAMPLES = REPO_ROOT / "examples"
GOLDEN_DIR = EXAMPLES / "golden-coaxial-power-chain"
GOLDEN_IR = GOLDEN_DIR / "golden-coaxial-power-chain.ir.json"
GOLDEN_SYSML = GOLDEN_DIR / "golden-coaxial-power-chain.sysml"

if str(MCP_SERVER) not in sys.path:
    sys.path.insert(0, str(MCP_SERVER))

from tools.generator import generate_sysml  # noqa: E402,F401
from tools.query import query_model  # noqa: E402,F401
from tools.sysml_lint import (  # noqa: E402,F401
    extract_connections,
    extract_declarations,
    lint_sysml,
    roundtrip_check,
)
from tools.validator import load_model, validate_model_json  # noqa: E402,F401


def base_model() -> Dict[str, Any]:
    """一个**完全合法且零 warning**的基准模型。

    覆盖全部 6 种 kind，并保证：需求既被满足又被验证、每个 PartDefinition 都被实例化。
    """
    return {
        "schema": "sysml-ir/v1",
        "package": "Demo",
        "elements": [
            {
                "id": "PART-DEF-MOTOR",
                "kind": "PartDefinition",
                "name": "Motor",
                "owner": "Demo",
                "properties": {"description": "无刷电机。"},
            },
            {
                "id": "PART-USE-MOTOR",
                "kind": "PartUsage",
                "name": "motorOne",
                "owner": "Demo",
                "properties": {"typeRef": "PART-DEF-MOTOR", "quantity": 4, "description": "四台电机。"},
            },
            {
                "id": "REQ-A",
                "kind": "Requirement",
                "name": "ReqAlpha",
                "owner": "Demo",
                "properties": {
                    "text": "转速不低于 1000 rpm",
                    "acceptanceCriteria": "稳态转速 n >= 1000 rpm",
                    "verifyMethod": "simulation",
                    "priority": "high",
                    "minSpeedRpm": 1000.0,
                },
                "relations": [
                    {"type": "satisfiedBy", "target": "PART-USE-MOTOR", "rationale": "由电机选型满足"},
                ],
            },
            {
                "id": "ACT-A",
                "kind": "ActionDefinition",
                "name": "ActAlpha",
                "owner": "Demo",
                "properties": {
                    "description": "转速校核动作。",
                    "inputs": [{"name": "commandRpm", "typeRef": "Real", "unit": "rpm"}],
                    "outputs": [{"name": "measuredRpm", "typeRef": "Real", "unit": "rpm"}],
                },
                "relations": [
                    {"type": "verifies", "target": "REQ-A", "rationale": "仿真校验转速指标"},
                ],
            },
            {
                "id": "STATE-A",
                "kind": "StateDefinition",
                "name": "MotorStates",
                "owner": "Demo",
                "properties": {
                    "description": "电机启停状态机。",
                    "states": ["Idle", "Running"],
                    "initial": "Idle",
                    "transitions": [{"from": "Idle", "to": "Running", "trigger": "start command"}],
                },
            },
            {
                "id": "ATTR-A",
                "kind": "Attribute",
                "name": "ratedVoltage",
                "owner": "Demo",
                "properties": {"valueType": "Real", "defaultValue": 24.0, "unit": "V"},
            },
        ],
    }


def extended_model() -> Dict[str, Any]:
    """在 ``base_model`` 基础上补齐 v1 增补的两种 kind（Constraint / Connection）。

    保持「完全合法且零 warning」：新增的 PartDefinition 被 PartUsage 实例化，
    Connection 两端都是同 owner（Demo）的 PartUsage，Constraint 只引用 Attribute。
    供新 kind 的正反例、渲染与回验使用；不改动 ``base_model`` 本身（其他测试在依赖它）。
    """
    model = copy.deepcopy(base_model())
    model["elements"].extend(
        [
            {
                "id": "PART-DEF-ESC",
                "kind": "PartDefinition",
                "name": "SpeedController",
                "owner": "Demo",
                "properties": {"description": "电子调速器。"},
            },
            {
                "id": "PART-USE-ESC",
                "kind": "PartUsage",
                "name": "escUnit",
                "owner": "Demo",
                "properties": {"typeRef": "PART-DEF-ESC", "quantity": 2, "description": "两路电调。"},
            },
            {
                "id": "CONSTRAINT-ENDURANCE",
                "kind": "Constraint",
                "name": "EnduranceBudget",
                "owner": "Demo",
                "properties": {
                    "expression": "T = ratedVoltage / 2.0",
                    "parameters": ["ATTR-A"],
                    "description": "占位公式，仅用于演示 Constraint 的渲染与回验。",
                },
            },
            {
                "id": "CONN-MOTOR-ESC",
                "kind": "Connection",
                "name": "motorToEsc",
                "owner": "Demo",
                "properties": {
                    "sourceRef": "PART-USE-MOTOR",
                    "targetRef": "PART-USE-ESC",
                    "flowKind": "electrical",
                    "description": "电机由电调驱动。",
                },
            },
        ]
    )
    return model


def mutate(model: Dict[str, Any], **changes: Any) -> Dict[str, Any]:
    """浅层改顶层字段。"""
    clone = copy.deepcopy(model)
    clone.update(changes)
    return clone


def element(model: Dict[str, Any], element_id: str) -> Dict[str, Any]:
    for item in model["elements"]:
        if item.get("id") == element_id:
            return item
    raise KeyError(element_id)


def edit_element(model: Dict[str, Any], element_id: str, mutate_fn) -> Dict[str, Any]:
    """对某个元素做一次修改，返回新模型（深拷贝，不污染基准模型）。"""
    clone = copy.deepcopy(model)
    mutate_fn(element(clone, element_id))
    return clone


def codes(result: Dict[str, Any], bucket: str = "errors") -> List[str]:
    return [item["code"] for item in result.get(bucket, [])]


def golden_model() -> Dict[str, Any]:
    return load_model(GOLDEN_IR)


__all__ = [
    "base_model",
    "extended_model",
    "mutate",
    "edit_element",
    "element",
    "codes",
    "golden_model",
    "load_model",
    "validate_model_json",
    "generate_sysml",
    "query_model",
    "lint_sysml",
    "extract_declarations",
    "extract_connections",
    "roundtrip_check",
    "GOLDEN_IR",
    "GOLDEN_SYSML",
    "REPO_ROOT",
    "MCP_SERVER",
    "json",
]
