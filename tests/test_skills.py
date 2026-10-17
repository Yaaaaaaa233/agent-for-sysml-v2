"""T5 —— 五份 skill 的结构要求。

任务书对 skill 有**可检验的硬性要求**，这里把它们钉住，
免得日后改写时把内容写薄了却没人发现：

- ``modeling-workflow``：**9 步** SOP，每步有输入/产出/自检；
- ``element-choice``：决策树 + **至少 4 个边界案例**，含「需求 vs 约束」「状态 vs 动作」「Definition vs Usage」；
- ``anti-patterns``：**至少 8 条**条目，格式为「错误现象 / 为什么错 / 正确做法」，
  且覆盖任务书点名的若干具体条目；
- ``worked-examples``：**恰好 5 个**范例，每个都走「一句话需求 → 分类判断 → IR JSON →
  关键渲染片段 → 校验结果 → 追溯落点 → 为什么这么选」，且含**1 个先错后改**的反例；
- ``domain-patterns``：**恰好 5 个**领域模式，每个都有「什么时候用 / 骨架片段 / 常见错法」，
  覆盖功率链、功率公式、续航分解、单桨失效、约束区间。

另外把两个新 skill 的 ``examples/`` 里的 IR 模型跑一遍真校验：合法样本必须 0 error，
「先错后改」的错误样本必须报出预期的错误码——文档里的说法要能被工具证伪。
"""

from __future__ import annotations

import json
import re
import unittest

from _support import REPO_ROOT, generate_sysml, load_model, validate_model_json

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

    def test_notes_that_traceability_tool_is_available(self):
        """``traceability`` 已实现：第 8 步必须直接用它，而不是「MVP 用 query_model 等价执行」。"""
        step8 = re.split(r"\n## 第 \d+ 步", self.text)[8]
        self.assertIn("traceability", step8)
        for field in ("gaps", "focus="):
            self.assertIn(field, step8, msg="第 8 步没有写 %s" % field)
        self.assertIn("matrix", step8)
        # 旧叙述必须清零
        self.assertNotIn("尚未提供", self.text)
        self.assertNotIn("MVP 用 `query_model` 等价执行", self.text)

    def test_lists_the_eight_tools_of_the_current_release(self):
        """工具清单要覆盖 8 个已实现工具（parse/export 按任务书口径写「已实现」）。"""
        for tool in (
            "query_model",
            "validate_model_json",
            "generate_sysml",
            "verify_sysml",
            "patch_model",
            "traceability",
            "parse_sysml",
            "export_simulink",
        ):
            self.assertIn(tool, self.text, msg="工具清单缺少 %s" % tool)
        self.assertIn("8 个", self.text)

    def test_step_six_treats_constraint_as_supported_v1_addition(self):
        step6 = re.split(r"\n## 第 \d+ 步", self.text)[6]
        self.assertIn("Constraint", step6)
        self.assertIn("v1 增补 kind", step6)
        self.assertNotIn("还没有正式的 `Constraint`", step6)


class TestElementChoice(unittest.TestCase):
    def setUp(self):
        self.text = read_skill("element-choice")

    def test_has_decision_tree(self):
        self.assertIn("决策树", self.text)
        for fork in ("岔路口 A", "岔路口 B", "岔路口 C", "岔路口 D"):
            self.assertIn(fork, self.text, msg="缺少 %s" % fork)

    def test_fork_count_is_four_everywhere(self):
        """开头说「几个岔路口」必须与正文 A–D 的个数一致（不许说三、正文却有四）。"""
        self.assertIn("四个岔路口", self.text)
        self.assertNotIn("三个岔路口", self.text)
        self.assertIn("## §2 四个岔路口的 30 秒版", self.text)
        section = self.text.split("## §2", 1)[1].split("## §3", 1)[0]
        for fork in ("| A ", "| B ", "| C ", "| D "):
            self.assertIn(fork, section, msg="§2 速查表缺少 %r 行" % fork)

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
            "Constraint",
            "Connection",
        ):
            self.assertIn(kind, self.text)
        self.assertIn("8 种 kind", self.text)

    def test_marks_constraint_as_v1_addition_not_invented(self):
        """Constraint/Connection 是 v1 增补 kind（已支持）；仍禁止自创第 9 种。"""
        self.assertIn("v1 增补 kind", self.text)
        self.assertIn("E-KIND-INVALID", self.text)
        self.assertNotIn("MVP 没有正式的 Constraint 元素", self.text)
        self.assertNotIn("Constraint` 元素是二期", self.text)


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

    def test_entry_nine_lists_all_eight_kinds_and_keeps_constraint_legal(self):
        body = self.entries()[8]
        for kind in ("Constraint", "Connection"):
            self.assertIn(kind, body, msg="第 9 条没提 %s" % kind)
        self.assertIn("8 种 kind", body)
        self.assertIn("v1 增补 kind", body)
        self.assertNotIn(
            '"kind": "Constraint"',
            body,
            msg="Constraint 已收录，不能再当「自创 kind」的反例",
        )

    def test_does_not_copy_textbook_definitions(self):
        """方案 6.1：skill 只写程序性知识，禁止抄教科书定义。"""
        forbidden = ("Metamodel", "元模型（Metamodel）：描述", "SysML 是一种", "OMG 标准定义")
        for phrase in forbidden:
            self.assertNotIn(phrase, self.text)


# --------------------------------------------------------------------------------------
# 二期补齐的两份 skill
# --------------------------------------------------------------------------------------

NEW_SKILLS = ("worked-examples", "domain-patterns")


def read_doc(name):
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def example_links(text):
    """文档里引用的 ``examples/*.ir.json`` 相对路径。"""
    return sorted(set(re.findall(r"\((examples/[A-Za-z0-9._-]+\.ir\.json)\)", text)))


class TestNewSkillFrontmatter(unittest.TestCase):
    """DSH 的目录 bundle 格式：两份新 skill 必须与三份旧 skill 同构。"""

    def test_skill_dirs_exist(self):
        for name in NEW_SKILLS:
            self.assertTrue((SKILLS / name / "SKILL.md").is_file(), msg=name)

    def test_frontmatter_has_required_keys(self):
        for name in NEW_SKILLS:
            text = read_doc(name)
            self.assertTrue(text.startswith("---"), msg=name)
            block = frontmatter(text)
            for key in ("name:", "description:", "Triggers:"):
                self.assertIn(key, block, msg="%s 缺少 %s" % (name, key))

    def test_name_field_matches_directory(self):
        for name in NEW_SKILLS:
            block = frontmatter(read_doc(name))
            self.assertRegex(block, r"name:\s*%s\b" % re.escape(name))

    def test_metadata_declares_version_and_related_skills(self):
        for name in NEW_SKILLS:
            block = frontmatter(read_doc(name))
            self.assertRegex(block, r'version:\s*"\d+\.\d+\.\d+"', msg=name)
            self.assertIn("last_updated:", block, msg=name)
            # 新 skill 必须能顺着 related_skills 找到入口与选型/反模式
            for related in ("modeling-workflow", "element-choice"):
                self.assertIn(related, block, msg="%s 的 related_skills 缺少 %s" % (name, related))

    def test_every_skill_example_link_points_at_a_real_file(self):
        for name in NEW_SKILLS:
            text = read_doc(name)
            links = example_links(text)
            self.assertGreaterEqual(len(links), 5, msg="%s 的范例链接太少" % name)
            for link in links:
                self.assertTrue((SKILLS / name / link).is_file(), msg="%s/%s 不存在" % (name, link))


class TestWorkedExamples(unittest.TestCase):
    def setUp(self):
        self.text = read_doc("worked-examples")

    def bodies(self):
        return re.split(r"\n## 范例 \d+", self.text)[1:]

    def test_has_exactly_five_examples_numbered_in_order(self):
        numbers = re.findall(r"\n## 范例 (\d+)", self.text)
        self.assertEqual(numbers, ["1", "2", "3", "4", "5"], msg="范例必须恰好 5 个且按 1~5 编号")
        self.assertEqual(len(self.bodies()), 5)

    def test_every_example_follows_the_seven_stage_skeleton(self):
        stages = (
            "**一句话需求**",
            "**分类判断**",
            "**IR JSON**",
            "**关键渲染片段**",
            "**校验结果**",
            "**追溯落点**",
            "**为什么这么选**",
        )
        for index, body in enumerate(self.bodies(), 1):
            for stage in stages:
                self.assertIn(stage, body, msg="范例 %d 缺少阶段 %s" % (index, stage))

    def test_every_example_explains_why_with_fork_and_anti_pattern(self):
        """「为什么这么选」不能只说结论：要引决策树岔路口与反模式条目号。"""
        for index, body in enumerate(self.bodies(), 1):
            self.assertIn("岔路口", body, msg="范例 %d 没引决策树岔路口" % index)
            self.assertRegex(body, r"反模式第 \d+ 条", msg="范例 %d 没引反模式条目号" % index)

    def test_has_exactly_one_before_after_counterexample(self):
        flagged = [body for body in self.bodies() if "先错后改" in body]
        self.assertEqual(len(flagged), 1, msg="必须恰好有 1 个「先错后改」反例")
        body = flagged[0]
        # 错误版本必须真的触发校验错误码，改后要给出纠正
        for code in ("E-PROP-THRESHOLD-STRING", "E-REL-TARGET-DANGLING"):
            self.assertIn(code, body, msg="反例没有引用真实错误码 %s" % code)
        self.assertIn("改后版本", body, msg="反例缺少「改后」对照")

    def test_counterexample_shows_that_quality_errors_escape_validation(self):
        """把常量写成需求不触发 error——这正是反模式第 5 条的要点，文档必须点破。"""
        body = [b for b in self.bodies() if "先错后改" in b][0]
        self.assertIn("反模式第 5 条", body)
        self.assertRegex(body, r"没有触发任何 error|不触发任何 error|没有触发")

    def test_marks_constraint_and_connection_as_v1_additions(self):
        for kind in ("Constraint", "Connection"):
            self.assertIn(kind, self.text, msg="没提到 v1 增补 kind %s" % kind)
        self.assertIn("v1 增补 kind", self.text)
        # 增补 kind 的关键字段要写对，别让 LLM 自己猜
        self.assertIn("parameters", self.text)
        self.assertIn("flowKind", self.text)

    def test_cites_real_error_codes_from_the_validator(self):
        for code in (
            "E-PROP-THRESHOLD-STRING",
            "E-REL-TARGET-DANGLING",
            "E-STATE-TRANSITION-ENDPOINT",
            "E-PARTUSAGE-TYPEREF-WRONGKIND",
            "W-REQ-NO-SATISFY",
        ):
            self.assertIn(code, self.text, msg="范例库没提到真实错误码 %s" % code)

    def test_every_example_marks_its_numbers_as_placeholders(self):
        self.assertIn("占位值", self.text)
        for index, body in enumerate(self.bodies(), 1):
            self.assertIn("占位", body, msg="范例 %d 没有标注占位值" % index)

    def test_reports_with_the_three_layer_discipline(self):
        for phrase in ("模型事实", "规范语义", "推断"):
            self.assertIn(phrase, self.text)

    def test_never_claims_official_parser_validation(self):
        for phrase in (
            "官方解析器验证",
            "已通过官方解析器验证",
            "通过官方解析器验证",
            "官方解析器验证通过",
            "已由官方解析器验证",
        ):
            self.assertNotIn(phrase, self.text, msg="诚实红线：不得声称 %s" % phrase)
        self.assertIn("不得当作实测结论", self.text)


class TestDomainPatterns(unittest.TestCase):
    def setUp(self):
        self.text = read_doc("domain-patterns")

    def bodies(self):
        return re.split(r"\n## 模式 \d+", self.text)[1:]

    def test_has_exactly_five_patterns_numbered_in_order(self):
        numbers = re.findall(r"\n## 模式 (\d+)", self.text)
        self.assertEqual(numbers, ["1", "2", "3", "4", "5"])
        self.assertEqual(len(self.bodies()), 5)

    def test_every_pattern_has_usage_skeleton_and_pitfalls(self):
        for index, body in enumerate(self.bodies(), 1):
            for marker in ("**什么时候用**", "**骨架片段**", "**常见错法**"):
                self.assertIn(marker, body, msg="模式 %d 缺少 %s" % (index, marker))
            self.assertIn("- [ ]", body, msg="模式 %d 没有可勾选的自检项" % index)

    def test_every_pattern_has_a_mini_ir_or_render_fragment(self):
        for index, body in enumerate(self.bodies(), 1):
            self.assertIn("```", body, msg="模式 %d 没有代码片段" % index)
            self.assertTrue(
                "json" in body or "渲染" in body,
                msg="模式 %d 的片段既不是 IR 也不是渲染" % index,
            )

    def test_covers_the_five_named_patterns(self):
        titles = {
            1: ("功率链", "电调"),
            2: ("Constraint", "Attribute"),
            3: ("续航", "分解"),
            4: ("单桨失效", "状态机"),
            5: ("约束区间", "转速比"),
        }
        bodies = self.bodies()
        for index, keywords in titles.items():
            body = bodies[index - 1]
            for keyword in keywords:
                self.assertIn(keyword, body, msg="模式 %d 没覆盖 %s" % (index, keyword))

    def test_keeps_the_endurance_decomposition_conclusion_consistent(self):
        """与 element-choice 案例 8 保持一致：拆到「单条可被一个部件或功能满足」为止。"""
        self.assertIn("单条可被一个部件或一个功能满足", self.text)

    def test_every_pattern_marks_placeholders(self):
        for index, body in enumerate(self.bodies(), 1):
            self.assertIn("占位", body, msg="模式 %d 没有标注占位值" % index)

    def test_never_claims_official_parser_validation(self):
        for phrase in (
            "官方解析器验证",
            "已通过官方解析器验证",
            "通过官方解析器验证",
            "官方解析器验证通过",
            "已由官方解析器验证",
        ):
            self.assertNotIn(phrase, self.text, msg="诚实红线：不得声称 %s" % phrase)
        self.assertIn("不得当作实测结论", self.text)


class TestSkillExampleModels(unittest.TestCase):
    """文档里的 IR 片段必须能跑：合法样本 0 error，错误样本报出预期码。"""

    def valid_files(self, skill):
        directory = SKILLS / skill / "examples"
        return sorted(
            path for path in directory.glob("*.ir.json") if not path.name.endswith(".before.ir.json")
        )

    def test_example_inventory(self):
        self.assertEqual(len(self.valid_files("worked-examples")), 5)
        self.assertEqual(len(self.valid_files("domain-patterns")), 5)
        before = list((SKILLS / "worked-examples" / "examples").glob("*.before.ir.json"))
        self.assertEqual(len(before), 1, msg="先错后改的错误样本必须恰好 1 个")

    def test_all_valid_examples_validate_clean_and_render(self):
        for skill in NEW_SKILLS:
            for path in self.valid_files(skill):
                model = load_model(path)
                result = validate_model_json(model)
                self.assertTrue(result["ok"], msg="%s: %s" % (path, result["errors"]))
                self.assertEqual(result["errors"], [], msg=str(path))
                generation = generate_sysml(model)
                self.assertTrue(generation["ok"], msg="%s: %s" % (path, generation["errors"]))
                self.assertIn(model["package"], generation["text"])
                self.assertTrue(generation["text"].strip())

    def test_example_generation_is_deterministic(self):
        for skill in NEW_SKILLS:
            for path in self.valid_files(skill):
                model = load_model(path)
                self.assertEqual(
                    generate_sysml(model)["sha256"],
                    generate_sysml(model)["sha256"],
                    msg=str(path),
                )

    def test_error_example_fails_with_the_expected_codes(self):
        path = SKILLS / "worked-examples" / "examples" / "05-constant-as-requirement.before.ir.json"
        model = load_model(path)
        result = validate_model_json(model)
        self.assertFalse(result["ok"], msg="错误样本必须被校验拦下")
        codes = [item["code"] for item in result["errors"]]
        for expected in ("E-PROP-THRESHOLD-STRING", "E-REL-TARGET-DANGLING"):
            self.assertIn(expected, codes, msg="错误样本没报 %s：%s" % (expected, codes))
        # 先校验后生成：有 error 时生成器必须拒绝渲染
        generation = generate_sysml(model)
        self.assertFalse(generation["ok"])
        self.assertIn("拒绝渲染", generation.get("message", ""))

    def test_error_example_proves_constant_as_requirement_is_not_caught(self):
        """把常量写成需求不产生 error——校验只抓结构，文档里的教学点必须成立。"""
        path = SKILLS / "worked-examples" / "examples" / "05-constant-as-requirement.before.ir.json"
        model = load_model(path)
        result = validate_model_json(model)
        error_elements = {item.get("element") for item in result["errors"]}
        self.assertIn("REQ-ENDURANCE", error_elements)
        self.assertNotIn("REQ-NOMINAL-VOLTAGE", error_elements)
        warning_codes = [
            item["code"] for item in result["warnings"] if item.get("element") == "REQ-NOMINAL-VOLTAGE"
        ]
        self.assertIn("W-REQ-NO-SATISFY", warning_codes)

    def test_example_models_are_well_formed_json(self):
        for skill in NEW_SKILLS:
            for path in (SKILLS / skill / "examples").glob("*.ir.json"):
                with path.open(encoding="utf-8") as handle:
                    model = json.load(handle)
                self.assertEqual(model["schema"], "sysml-ir/v1", msg=str(path))


class TestSkillNarrativeConsistency(unittest.TestCase):
    """二期增补（Constraint/Connection、traceability 等）落地后，skill 的「现状」叙述必须同步。

    这些断言专门钉「过时叙述」：kind 数量、二期口径、traceability 是否可用，
    以及 element-choice 案例 3 与 anti-patterns 第 16 条是否自相矛盾。
    """

    ALL = (
        "modeling-workflow",
        "element-choice",
        "anti-patterns",
        "worked-examples",
        "domain-patterns",
    )

    def texts(self):
        return {name: read_doc(name) for name in self.ALL}

    def test_no_skill_still_claims_six_kinds(self):
        for name, text in self.texts().items():
            for phrase in ("6 种 kind", "六种 kind", "只有 6 种"):
                self.assertNotIn(phrase, text, msg="%s 仍在写「%s」" % (name, phrase))

    def test_no_skill_claims_traceability_or_constraint_is_missing(self):
        stale = (
            "尚未提供",
            "MVP 尚未",
            "MVP 没有正式的 `Constraint`",
            "正式的 `Constraint` 元素是二期",
            "等 `Constraint` 落地",
        )
        for name, text in self.texts().items():
            for phrase in stale:
                self.assertNotIn(phrase, text, msg="%s 仍有过时叙述「%s」" % (name, phrase))

    def test_element_choice_case_three_keeps_initial_edge_trigger_free(self):
        """案例 3 必须与 anti-patterns 第 16 条一致：initial 的出边不挂 trigger/guard。"""
        text = read_doc("element-choice")
        body = re.split(r"\n### 案例 3", text)[1].split("\n### 案例 4")[0]
        self.assertIn('"initial": "Standby"', body)
        # 初始出边：没有 trigger / guard
        self.assertIn('{ "from": "Standby", "to": "Grounded" }', body)
        # 事件迁移从非初始态出发
        self.assertIn(
            '{ "from": "Grounded", "to": "Climbing", "trigger": "takeoff command" }',
            body,
        )
        self.assertRegex(body, r"为什么 `initial` 出边不挂 `trigger`")
        self.assertIn("反模式第 16 条", body)

    def test_anti_pattern_sixteen_still_states_the_rule_case_three_follows(self):
        text = read_doc("anti-patterns")
        self.assertIn("`initial` 的出边一律不写 `trigger` / `guard`", text)

    def test_skills_agree_on_constraint_as_a_legal_kind(self):
        """三份讲选型的 skill 都要把 Constraint 当合法 kind，而不是「自创」。"""
        self.assertIn("v1 增补 kind", read_doc("element-choice"))
        self.assertIn("v1 增补 kind", read_doc("anti-patterns"))
        self.assertIn("v1 增补 kind", read_doc("modeling-workflow"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
