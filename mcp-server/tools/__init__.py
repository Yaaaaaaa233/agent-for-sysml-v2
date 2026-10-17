"""SysML v2 建模智能体 —— 工具包。

八个 MCP 工具（技术方案 5.2 / 9.1 的 T2 + 二期 T7–T10）：

- ``validate_model_json`` —— ``tools.validator``
- ``generate_sysml``      —— ``tools.generator``
- ``query_model``         —— ``tools.query``
- ``verify_sysml``        —— ``tools.sysml_lint``（lint + 元素级比对）+ 可选 ``tools.official_parser``
- ``patch_model``         —— ``tools.patch``（原子增量编辑）
- ``traceability``        —— ``tools.trace``（矩阵 / 缺口 / 影响面）
- ``parse_sysml``         —— ``tools.parser``（文本 → IR，子集逆解析）
- ``export_simulink``     —— ``tools.export``（CSV / JSON / MD 参数表）

所有工具都是纯函数式：入参与返回值均为 JSON 可序列化结构，不做任何 I/O 副作用
（``load_model`` / ``save_text`` 是显式的辅助函数，不参与工具契约）。

导入本包不会拉起官方解析器后端：``parse_with_official`` 只在真正调用时才探测 JVM 与
kernel，后端缺席时如实返回 ``status="unavailable"``。
"""

from .validator import load_model, validate_model_json  # noqa: F401
from .generator import generate_sysml  # noqa: F401
from .query import query_model  # noqa: F401
from .sysml_lint import (  # noqa: F401
    extract_connections,
    extract_declarations,
    lint_sysml,
    roundtrip_check,
)
from .patch import patch_model  # noqa: F401
from .trace import traceability  # noqa: F401
from .parser import parse_sysml  # noqa: F401
from .export import export_simulink  # noqa: F401
from .official_parser import detect_backend, parse_with_official  # noqa: F401

__all__ = [
    "validate_model_json",
    "generate_sysml",
    "query_model",
    "patch_model",
    "traceability",
    "parse_sysml",
    "export_simulink",
    "detect_backend",
    "parse_with_official",
    "load_model",
    "lint_sysml",
    "extract_declarations",
    "extract_connections",
    "roundtrip_check",
]

__version__ = "1.1.0"
SCHEMA_ID = "sysml-ir/v1"
