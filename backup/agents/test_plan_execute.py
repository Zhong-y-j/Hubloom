"""兼容入口 → ``python -m agents.scripts.plan_demo``。"""

from agents.scripts.plan_demo import main

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
