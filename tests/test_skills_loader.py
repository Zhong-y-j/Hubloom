"""Skills 目录扫描与黑名单过滤单元测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agents.adp.chat import build_chat_system_prompt
from agents.adp.thought import ThoughtPhase, build_respond_prompt
from hubloom.config import HubloomConfig
from skills.loader import load_skills, load_skills_prompt, resolve_skills_root


def _write_skill(root: Path, skill_id: str, body: str, *, with_frontmatter: bool = True) -> None:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    if with_frontmatter:
        text = f"---\nname: {skill_id}\ndescription: test\n---\n\n{body}\n"
    else:
        text = body + "\n"
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")


class SkillsLoaderTests(unittest.TestCase):
    def test_resolve_relative_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills").mkdir()
            resolved = resolve_skills_root("skills", project_root=root)
            self.assertEqual(resolved, (root / "skills").resolve())

    def test_load_all_sorted_and_strip_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_root = root / "skills"
            _write_skill(skills_root, "zeta", "# Zeta\n\nZ content.")
            _write_skill(skills_root, "alpha", "# Alpha\n\nA content.")
            # 无 SKILL.md 的目录应忽略
            (skills_root / "empty").mkdir()
            (skills_root / "empty" / "README.md").write_text("x", encoding="utf-8")

            loaded = load_skills("skills", project_root=root)
            self.assertEqual([s.skill_id for s in loaded], ["alpha", "zeta"])
            self.assertTrue(loaded[0].body.startswith("# Alpha"))
            self.assertNotIn("description:", loaded[0].body)

    def test_exclude_blacklist_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_root = root / "skills"
            _write_skill(skills_root, "a2ui", "# A2UI")
            _write_skill(skills_root, "hubloom", "# Hubloom")

            loaded = load_skills("skills", exclude=["A2UI"], project_root=root)
            self.assertEqual([s.skill_id for s in loaded], ["hubloom"])

            prompt = load_skills_prompt("skills", exclude=["a2ui"], project_root=root)
            self.assertIn("hubloom", prompt)
            self.assertNotIn("A2UI", prompt)
            self.assertIn("# Agent Skills", prompt)

    def test_missing_dir_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(load_skills("skills", project_root=root), [])
            self.assertEqual(load_skills_prompt("skills", project_root=root), "")

    def test_config_skills_exclude_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "env.yaml"
            cfg_path.write_text(
                "skills_dir: custom_skills\nskills_exclude:\n  - a2ui\n  - Other\n",
                encoding="utf-8",
            )
            cfg = HubloomConfig.from_file(cfg_path)
            self.assertEqual(cfg.skills_dir, "custom_skills")
            self.assertEqual(cfg.skills_exclude, ["a2ui", "Other"])


class SkillsPromptInjectTests(unittest.TestCase):
    def test_chat_order_base_skills_catalog(self) -> None:
        prompt = build_chat_system_prompt(
            None,
            catalog_snippet="## CATALOG_MARKER\ncatalog",
            skills_snippet="# Agent Skills\nskills-body",
        )
        i_base = prompt.index("你是 **Hubloom**")
        i_skills = prompt.index("Agent Skills")
        i_catalog = prompt.index("CATALOG_MARKER")
        self.assertLess(i_base, i_skills)
        self.assertLess(i_skills, i_catalog)

    def test_skills_only_in_respond_not_thought(self) -> None:
        from agents.adp.thought import (
            build_deliberate_prompt,
            build_execute_prompt,
            build_respond_prompt,
        )

        skills = "# Agent Skills\na2ui-rules"
        deliberate = build_deliberate_prompt(None, ThoughtPhase.BEFORE_EXECUTE)
        execute = build_execute_prompt(None)
        respond = build_respond_prompt(skills_snippet=skills)
        self.assertNotIn("a2ui-rules", deliberate)
        self.assertNotIn("a2ui-rules", execute)
        self.assertIn("a2ui-rules", respond)
        self.assertLess(respond.index("正式回复"), respond.index("a2ui-rules"))


if __name__ == "__main__":
    unittest.main()
