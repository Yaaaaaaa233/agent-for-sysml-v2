"""T7 —— 往返一致性（generate → parse → validate → generate）。

验收口径（任务 B）：

1. 对下列 IR：``generate_sysml`` → ``parse_sysml`` → ``validate_model_json`` ok
   → 再 ``generate_sysml``，要求 **IR 元素级等价**（id/kind/name/owner/properties/
   relations；meta 不参与）且 **两次生成逐字节一致**（sha256 相等）。
2. 手写同子集文本：解析后 regenerate 必须稳定（parse → generate → parse → generate
   的 IR 等价、字节一致）。

覆盖清单：
- 标杆案例 IR；
- ``tests/_support.py`` 的 ``base_model`` / ``extended_model``；
- ``docs/demo`` 与 ``docs/demo/run-cruise-endurance-4h`` 下实际存在的 IR 文件
  （**不解析**这些目录里存档的旧格式 .sysml，一律从 IR 重新 generate）；
- 一段覆盖八种 kind、单位、状态机、Constraint、Connection、relations 的手写文本。
"""

from __future__ import annotations

import copy
import unittest

from _support import (
    GOLDEN_IR,
    REPO_ROOT,
    base_model,
    extended_model,
    generate_sysml,
    load_model,
    validate_model_json,
)

from tools.parser import parse_sysml

#: task B 明确点名的存档 IR（只读取 IR，不读取同目录的 .sysml 历史产物）
DEMO_IR_FILES = (
    REPO_ROOT / "docs" / "demo" / "step0-before.ir.json",
    REPO_ROOT / "docs" / "demo" / "step2-revised.ir.json",
    REPO_ROOT / "docs" / "demo" / "step4-final.ir.json",
    REPO_ROOT
    / "docs"
    / "demo"
    / "run-cruise-endurance-4h"
    / "step2-revised.ir.json",
    REPO_ROOT
    / "docs"
    / "demo"
    / "run-cruise-endurance-4h"
    / "step4-final.ir.json",
)

#: 手写变体：不依赖生成器，覆盖八种 kind + 单位 + 状态机 + Constraint/Connection + relations
HAND_WRITTEN = """\
// 手写变体（同渲染子集）：状态机 / 单位 / Constraint / Connection / relations
package HandWritten {
    private import ScalarValues::*;
    private import SI::*;

    // ---- PartDefinition ----
    // id: PART-DEF-MOTOR
    // description: 无刷电机。
    part def Motor {
        // id: ATTR-RATED-VOLTAGE
        // description: 额定电压。
        attribute ratedVoltage : Real = 24.0 [V];
    }
    // id: PART-DEF-BASE
    abstract part def BasePart;

    // ---- PartUsage ----
    // id: PART-USE-MOTOR-A
    // description: 主电机。
    part motorA : Motor[2] {
        // 追溯关系 (relations):
        //   PART-USE-MOTOR-A --connects--> PART-USE-MOTOR-B  (同型备份)
    }
    // id: PART-USE-MOTOR-B
    part motorB : Motor[2];
    // id: PART-USE-BASE
    part baseOne : BasePart;

    // ---- Requirement ----
    // id: REQ-SPEED
    requirement def SpeedRequirement {
        doc /* 转速不低于 1000 rpm */
        doc /* 验收判据: 稳态转速 n >= 1000 rpm */
        attribute verifyMethod : String = "test";
        attribute priority : String = "high";
        attribute source : String = "任务书";
        attribute rationale : String = "可验证条目。";
        attribute minSpeed : Real = 1000.0 [rpm];
        attribute critical : Boolean = true;
        attribute budget : Real = 4.0 [h];
        // 追溯关系 (relations):
        //   REQ-SPEED --satisfiedBy--> PART-USE-MOTOR-A  (电机满足)
    }

    // ---- ActionDefinition ----
    // id: ACT-CHECK
    action def CheckSpeed {
        in command : Real;  // unit: rpm
        out measured : Real;  // unit: rpm
        // 追溯关系 (relations):
        //   ACT-CHECK --verifies--> REQ-SPEED  (实测校验)
    }

    // ---- StateDefinition ----
    // id: STATE-MOTOR
    state def MotorStates {
        entry; then Idle;
        state Idle;
        state Running;
        // trigger: start command
        transition Transition_Idle_to_Running_0 first Idle if (rpm > 1000) then Running;
        // trigger: stop command
        transition Transition_Running_to_Idle_1 first Running then Idle;
    }

    // ---- Attribute ----
    // id: ATTR-EFFICIENCY
    attribute motorEfficiency : Real = 0.85;

    // ---- Constraint ----
    // id: CONSTRAINT-VOLTAGE
    // description: 电压上限约束。
    constraint def VoltageLimit {
        // expression: ratedVoltage <= 26.0
        // parameters: ratedVoltage
    }

    // ---- Connection ----
    // Connection CONN-MOTOR-LINK flowKind=electrical name=motorLink description: 主备电机连接。
    connect motorA to motorB;
}
"""


def canonical(model):
    """元素级等价口径：以 id 为键，比较 kind/name/owner/properties/relations。"""
    elements = {}
    for element in model["elements"]:
        elements[element["id"]] = {
            "kind": element["kind"],
            "name": element["name"],
            "owner": element["owner"],
            "properties": copy.deepcopy(element.get("properties") or {}),
            "relations": copy.deepcopy(element.get("relations") or []),
        }
    return elements


class RoundtripAssertions(unittest.TestCase):
    def assert_roundtrip(self, model, label):
        validation = validate_model_json(model)
        self.assertTrue(validation["ok"], msg="%s 原始 IR 不合法：%s" % (label, validation["errors"]))

        first = generate_sysml(model)
        self.assertTrue(first["ok"], msg="%s 生成失败：%s" % (label, first["errors"]))

        parsed = parse_sysml(first["text"])
        self.assertTrue(
            parsed["ok"],
            msg="%s 解析失败：%s / %s"
            % (label, parsed["errors"], parsed["unsupported"]),
        )
        self.assertEqual(parsed["unsupported"], [], msg="%s 出现子集外构造" % label)
        self.assertEqual(parsed["stats"]["synthesizedIds"], 0, msg="%s 丢了 id 注释" % label)

        reparsed_model = parsed["model"]
        self.assertTrue(
            validate_model_json(reparsed_model)["ok"],
            msg="%s 逆解析出的 IR 未通过校验：%s"
            % (label, validate_model_json(reparsed_model)["errors"]),
        )
        self.assertEqual(
            canonical(reparsed_model),
            canonical(model),
            msg="%s 的 IR 元素级不等价" % label,
        )

        second = generate_sysml(reparsed_model)
        self.assertTrue(second["ok"], msg="%s 二次生成失败：%s" % (label, second["errors"]))
        self.assertEqual(first["text"], second["text"], msg="%s 两次生成文本不一致" % label)
        self.assertEqual(first["sha256"], second["sha256"], msg="%s sha256 不一致" % label)
        return parsed


class TestIrRoundtrip(RoundtripAssertions):
    def test_golden_case(self):
        self.assert_roundtrip(load_model(GOLDEN_IR), "golden")

    def test_base_model(self):
        self.assert_roundtrip(base_model(), "base_model")

    def test_extended_model(self):
        self.assert_roundtrip(extended_model(), "extended_model")

    def test_demo_archives(self):
        for path in DEMO_IR_FILES:
            self.assertTrue(path.is_file(), msg="缺少演示存档：%s" % path)
            # 只读 IR；同目录的 .sysml 是旧格式历史记录，不参与解析
            self.assert_roundtrip(load_model(path), path.name)

    def test_roundtrip_with_custom_indent(self):
        """缩进只影响可读性；用同一 indent 重新生成必须逐字节一致。"""
        model = base_model()
        first = generate_sysml(model, indent="  ")
        parsed = parse_sysml(first["text"])
        self.assertTrue(parsed["ok"], msg=parsed["errors"])
        second = generate_sysml(parsed["model"], indent="  ")
        self.assertEqual(first["sha256"], second["sha256"])

    def test_generated_text_is_byte_stable_across_runs(self):
        model = load_model(GOLDEN_IR)
        first = generate_sysml(model)
        second = generate_sysml(model)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["text"], second["text"])


class TestHandWrittenRoundtrip(RoundtripAssertions):
    def test_hand_written_text_parses_cleanly(self):
        parsed = parse_sysml(HAND_WRITTEN)
        self.assertTrue(parsed["ok"], msg=parsed["errors"])
        self.assertEqual(parsed["unsupported"], [])
        self.assertEqual(parsed["warnings"], [])
        self.assertEqual(parsed["stats"]["elements"], 12)
        self.assertEqual(parsed["stats"]["synthesizedIds"], 0)
        validation = validate_model_json(parsed["model"])
        self.assertTrue(validation["ok"], msg=validation["errors"])

    def test_hand_written_regenerate_is_stable(self):
        first_parse = parse_sysml(HAND_WRITTEN)
        first_gen = generate_sysml(first_parse["model"])
        self.assertTrue(first_gen["ok"], msg=first_gen["errors"])

        second_parse = parse_sysml(first_gen["text"])
        self.assertTrue(second_parse["ok"], msg=second_parse["errors"])
        self.assertEqual(
            canonical(second_parse["model"]),
            canonical(first_parse["model"]),
            msg="手写文本经一次生成后 IR 漂移",
        )

        second_gen = generate_sysml(second_parse["model"])
        self.assertEqual(first_gen["text"], second_gen["text"])
        self.assertEqual(first_gen["sha256"], second_gen["sha256"])

    def test_hand_written_preserves_all_features(self):
        parsed = parse_sysml(HAND_WRITTEN)
        elements = {element["id"]: element for element in parsed["model"]["elements"]}
        self.assertTrue(elements["PART-DEF-BASE"]["properties"]["isAbstract"])
        self.assertEqual(elements["PART-USE-MOTOR-A"]["properties"]["quantity"], 2)
        self.assertEqual(elements["ATTR-RATED-VOLTAGE"]["properties"]["unit"], "V")
        self.assertEqual(
            elements["STATE-MOTOR"]["properties"]["transitions"][0],
            {
                "from": "Idle",
                "to": "Running",
                "trigger": "start command",
                "guard": "rpm > 1000",
            },
        )
        self.assertEqual(
            elements["CONSTRAINT-VOLTAGE"]["properties"],
            {
                "expression": "ratedVoltage <= 26.0",
                "parameters": ["ATTR-RATED-VOLTAGE"],
                "description": "电压上限约束。",
            },
        )
        self.assertEqual(elements["CONN-MOTOR-LINK"]["properties"]["flowKind"], "electrical")
        self.assertEqual(elements["CONN-MOTOR-LINK"]["name"], "motorLink")


class TestRoundtripRegressions(unittest.TestCase):
    """逆解析不能悄悄改语义：逐字段抽查 golden 产物。"""

    def test_wh_unit_survives_both_directions(self):
        model = load_model(GOLDEN_IR)
        text = generate_sysml(model)["text"]
        self.assertIn("[W*h]", text)
        parsed = parse_sysml(text)
        attribute = [
            e
            for e in parsed["model"]["elements"]
            if e["id"] == "ATTR-BATTERY-CAPACITY"
        ][0]
        self.assertEqual(attribute["properties"]["unit"], "Wh")
        self.assertIn("[W*h]", generate_sysml(parsed["model"])["text"])

    def test_connection_name_is_not_lost(self):
        model = load_model(GOLDEN_IR)
        parsed = parse_sysml(generate_sysml(model)["text"])
        names = {
            e["id"]: e["name"]
            for e in parsed["model"]["elements"]
            if e["kind"] == "Connection"
        }
        self.assertEqual(
            names,
            {
                "CONN-BATTERY-ESC": "batteryToEsc",
                "CONN-UPPER-MOTOR-PROP": "upperMotorToPropeller",
            },
        )

    def test_no_meta_is_required_from_parser(self):
        model = load_model(GOLDEN_IR)
        parsed = parse_sysml(generate_sysml(model)["text"])
        # meta 不参与元素级等价；解析器可以完全不产出它
        self.assertNotIn("meta", parsed["model"])
        self.assertEqual(parsed["model"]["schema"], "sysml-ir/v1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
