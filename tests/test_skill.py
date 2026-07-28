from skill.load import load_skills, build_skills_prompt
from tools.builtin.skill_tools import build_skill_tools
from tools.registry import ToolRegistry
from tools.runner import ToolRunner
import asyncio


# 1、加载 SKILL.md 文件，生成系统提示词
def test_load_skills():
    skills = load_skills("skills")
    prompt = build_skills_prompt(skills)
    print("【注入给 Agent 的系统提示词】")
    print(prompt)
    print("\n")


# 2、加载技能工具，生成工具注册表
def test_read_skill():
    skill_tools = build_skill_tools(
        skills_dir="skills",
    )
    registry = ToolRegistry.from_tools(skill_tools)

    print("【可用的工具列表】")
    for tool in registry.list_definitions():
        print("【工具名称】", tool["name"])
        print("【工具描述】", tool["description"])
        print("【工具参数】", tool["parameters"])
    print("\n")
    return registry


# 3、使用使用 read_skill 工具，执行工具返回 skill 的正文
def test_tool_runner():
    registry = test_read_skill()
    tool_runner = ToolRunner(registry)

    async def _run():
        text, is_error = await tool_runner.run(
            "read_skill",  # 工具名称
            {"skill": "account-access"},  # 工具参数
        )
        print("【工具执行结果】")
        print("【是否错误】", is_error)
        print("【执行结果】", text[:200])

    asyncio.run(_run())


if __name__ == "__main__":
    test_load_skills()
    test_tool_runner()
