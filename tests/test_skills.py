"""T5 —— T3 三份 skill 的结构要求。

任务书对三份 skill 有**可检验的硬性要求**，这里把它们钉住，
免得日后改写时把内容写薄了却没人发现：

- ``modeling-workflow``：**9 步** SOP，每步有输入/产出/自检；
- ``element-choice``：决策树 + **至少 4 个边界案例**，含「需求 vs 约束」「状态 vs 动作」「Definition vs Usage」；
- ``anti-patterns``：**至少 8 条**条目，格式为「错误现象 / 为什么错 / 正确做法」，
  且覆盖任务书点名的若干具体条目。
"""

from __future__ import annotations

import re
import unittest

from _support import REPO_ROOT

SKILLS = REPO_ROOT / "skills"


def read_skill(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def frontmatter(text: str) -> str:
    return text.split("---")[1]


class TestSkillFrontmatter(unittest.TestCase):
    """DSH 的格式要求：目录 bundle + 必填 name / description。"""

    def test_all_three_skills_exist(self):
        for name in ("modeling-workflow", "element-choice", "anti-patterns"):
            self.assertTrue((SKILLS / name / "SKILL.md").is_file(), msg=name)

    def test_frontmatter_has_required_keys(self):
        for name in ("modeling-workflow", "element-choice", "anti-patterns"):
            text = read_skill(name)
            self.assertTrue(text.startswith("---"), msg=name)
            block = frontmatter(text)
            self.assertIn("name:", block, msg=name)
            self.assertIn("description:", block, msg=name)

    def test_description_carries_triggers(self):
        """description 要能被「触发词」命中，否则 skill 不会被加载。"""
        for name in ("modeling-workflow", "element-choice", "anti-patterns"):
            block = frontmatter(read_skill(name))
            self.assertIn("Triggers:", block, msg=name)

    def test_name_field_matches_directory(self):
        for name in ("modeling-workflow", "element-choice", "anti-patterns"):
            block = frontmatter(read_skill(name))
            self.assertRegex(block, r"name:\s*%s\b" % re.escape(name))


class TestModelingWorkflow(unittest.TestCase):
    def setUp(self):
        self.text = read_skill("modeling-workflow")

    def test_has_exactly_nine_numbered_steps(self):
        for index in range(1, 10):
            self.assertIn("## 第 %d 步" % index, self.text, msg="缺少第 %d 步" % index)
        self.assertNotIn("## 第 10 步", self.text)

    def test_every_step_declares_input_output_and_selfcheck(self):
        """每步都必须有「输入 / 产出 / 自检」三段，否则 SOP 不完整。"""
        steps = re.split(r"\n## 第 \d+ 步", self.text)[1:]
        self.assertEqual(len(steps), 9)
        for index, body in enumerate(steps, 1):
            for marker in ("**输入**", "**产出**", "**自检**"):
                self.assertIn(marker, body, msg="第 %d 步缺少 %s" % (index, marker))
            self.assertIn("- [ ]", body, msg="第 %d 步的自检没有可勾选项" % index)

    def test_follows_the_fixed_tool_order(self):
        """方案 5.3：先查现状 → 填 JSON → 校验 → 生成 → 回验，顺序不能乱。"""
        positions = [
            self.text.index("query_model"),
            self.text.index("validate_model_json"),
            self.text.index("generate_sysml"),
            self.text.index("verify_sysml"),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_mentions_changing_json_not_text(self):
        self.assertIn("改 IR JSON", self.text)
        self.assertIn("不要改生成出来的文本", self.text.replace("手改", "不要改"))

    def test_notes_that_traceability_tool_is_phase_two(self):
        """MVP 没有 traceability 工具，SOP 必须如实说明用 query_model 等价执行。"""
        self.assertIn("traceability", self.text)
        self.assertIn("二期", self.text)


class TestElementChoice(unittest.TestCase):
    def setUp(self):
        self.text = read_skill("element-choice")

    def test_has_decision_tree(self):
        self.assertIn("决策树", self.text)
        for fork in ("岔路口 A", "岔路口 B", "岔路口 C", "岔路口 D"):
            self.assertIn(fork, self.text, msg="缺少 %s" % fork)

    def test_has_at_least_four_boundary_cases(self):
        cases = re.findall(r"### 案例 (\d+)", self.text)
        self.assertGreaterEqual(len(cases), 4, msg="边界案例只有 %d 个" % len(cases))

    def test_covers_the_three_required_boundaries(self):
        # 需求 vs 约束
        self.assertRegex(self.text, r"需求还是参数|需求 vs |是需求还是")
        # 状态 vs 动作
        self.assertIn("状态机还是动作", self.text)
        # Definition vs Usage
        self.assertIn("Definition 还是 Usage", self.text)

    def test_each_case_gives_a_decisive_criterion(self):
        bodies = re.split(r"\n### 案例 \d+", self.text)[1:]
        self.assertGreaterEqual(len(bodies), 4)
        for index, body in enumerate(bodies, 1):
            self.assertIn("决定性判据", body, msg="案例 %d 没给决定性判据" % index)
            self.assertIn("结论", body, msg="案例 %d 没给结论" % index)

    def test_lists_the_controlled_enumeration(self):
        for kind in (
            "PartDefinition",
            "PartUsage",
            "Requirement",
            "ActionDefinition",
            "StateDefinition",
            "Attribute",
        ):
            self.assertIn(kind, self.text)

    def test_forbids_inventing_constraint_kind(self):
        """MVP 没有 Constraint，选型 skill 必须明确说「别自创」，并指向二期。"""
        self.assertIn("Constraint", self.text)
        self.assertIn("E-KIND-INVALID", self.text)


class TestAntiPatterns(unittest.TestCase):
    def setUp(self):
        self.text = read_skill("anti-patterns")

    def entries(self):
        return re.split(r"\n## \d+\. ", self.text)[1:]

    def test_has_at_least_eight_entries(self):
        self.assertGreaterEqual(len(self.entries()), 8, msg="反模式只有 %d 条" % len(self.entries()))

    def test_every_entry_has_the_required_three_parts(self):
        for body in self.entries():
            for marker in ("**现象**", "**为什么错**", "**正确做法**"):
                self.assertIn(marker, body, msg="条目缺少 %s" % marker)

    def test_covers_the_named_anti_patterns(self):
        required = {
            "需求缺验收判据": "需求没有验收判据",
            "引用不存在元素": "引用了不存在的元素",
            "命名冲突": "命名冲突",
            "单位写进字符串": "把单位写进字符串",
            "把常量写成需求": "把常量写成需求",
            "功率链漏电调": "功率链漏掉电调",
        }
        for label, heading in required.items():
            self.assertIn(heading, self.text, msg="缺少任务书点名的条目：%s（%s）" % (label, heading))

    def test_cites_real_error_codes(self):
        """条目要能对着校验输出定位，所以必须引用真实错误码。"""
        for code in (
            "E-REQ-NO-ACCEPTANCE",
            "E-REL-TARGET-DANGLING",
            "E-NAME-DUP",
            "E-PROP-THRESHOLD-STRING",
            "E-PARTUSAGE-TYPEREF-DANGLING",
            "E-KIND-INVALID",
        ):
            self.assertIn(code, self.text, msg="没提到错误码 %s" % code)

    def test_states_that_validate_cannot_catch_quality_errors(self):
        """方案 10.1：validate 只抓结构错误。第 5 条必须点破这一点。"""
        self.assertIn("不抓建模质量错误", self.text.replace(" ", ""))

    def test_has_error_code_lookup_table(self):
        self.assertIn("错误码 → 该看哪一条", self.text)

    def test_does_not_copy_textbook_definitions(self):
        """方案 6.1：skill 只写程序性知识，禁止抄教科书定义。"""
        forbidden = ("Metamodel", "元模型（Metamodel）：描述", "SysML 是一种", "OMG 标准定义")
        for phrase in forbidden:
            self.assertNotIn(phrase, self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
