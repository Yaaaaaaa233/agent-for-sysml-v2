"""SysML v2 建模智能体 —— 工具包。

三个核心工具（技术方案 5.2 / 9.1 的 T2）：

- ``validate_model_json`` —— ``tools.validator``
- ``generate_sysml``      —— ``tools.generator``
- ``query_model``         —— ``tools.query``

外加 MVP 的回验底座 ``tools.sysml_lint``（见 ``docs/T0-调研结论.md`` 的解析底座选型）。

所有工具都是纯函数式：入参与返回值均为 JSON 可序列化结构，不做任何 I/O 副作用
（``load_model`` / ``save_text`` 是显式的辅助函数，不参与工具契约）。
"""

from .validator import validate_model_json, load_model  # noqa: F401
from .generator import generate_sysml  # noqa: F401
from .query import query_model  # noqa: F401
from .sysml_lint import lint_sysml, extract_declarations, roundtrip_check  # noqa: F401

__all__ = [
    "validate_model_json",
    "generate_sysml",
    "query_model",
    "load_model",
    "lint_sysml",
    "extract_declarations",
    "roundtrip_check",
]

__version__ = "1.0.0"
SCHEMA_ID = "sysml-ir/v1"
