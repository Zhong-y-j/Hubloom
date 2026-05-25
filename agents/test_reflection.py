"""兼容入口 → ``python -m agents.scripts.reflection_demo``。"""

from agents.scripts.reflection_demo import main

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
