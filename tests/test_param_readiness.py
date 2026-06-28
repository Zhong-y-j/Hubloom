import unittest

from agents.plan.models import ExecutionPlan, ExecutionStep
from tools.param_hints import format_tool_param_hints, params_for_user_clarification
from tools.param_readiness import (
    check_plan_readiness,
    is_deferred_arg,
    is_present,
    missing_required_fields,
)
from tools.base import BaseTool
from tools.registry import ToolRegistry


class _DetailTool(BaseTool):
    name = "getDetail"
    description = "detail"
    parameters = {
        "type": "object",
        "required": ["communityId"],
        "properties": {"communityId": {"type": "string"}},
    }

    async def execute(self, **kwargs):
        return "ok"


class _OrderTool(BaseTool):
    name = "placeOrder"
    description = "order"
    parameters = {
        "type": "object",
        "required": ["petId"],
        "properties": {"petId": {"type": "integer", "title": "宠物 ID"}},
    }

    async def execute(self, **kwargs):
        return "ok"


class ParamReadinessTests(unittest.TestCase):
    def test_is_present(self) -> None:
        self.assertFalse(is_present(None))
        self.assertFalse(is_present(""))
        self.assertFalse(is_present("   "))
        self.assertTrue(is_present(0))
        self.assertTrue(is_present(False))
        self.assertTrue(is_present([]))
        self.assertTrue(is_present("x"))

    def test_is_deferred_arg(self) -> None:
        self.assertTrue(is_deferred_arg("{{steps.1.body.id}}"))
        self.assertFalse(is_deferred_arg("plain"))

    def test_missing_required_fields(self) -> None:
        params = {
            "type": "object",
            "required": ["petId"],
            "properties": {"petId": {"type": "integer"}},
        }
        self.assertEqual(missing_required_fields(params, {}), ["petId"])
        self.assertEqual(missing_required_fields(params, {"petId": 0}), [])
        self.assertEqual(
            missing_required_fields(params, {"petId": "{{steps.1.id}}"}),
            [],
        )

    def test_skip_dependent_step(self) -> None:
        registry = ToolRegistry.from_tools([_DetailTool()])
        plan = ExecutionPlan(
            task_type="general_task",
            steps=[
                ExecutionStep(
                    step_id=2,
                    tool_name="getDetail",
                    tool_args={},
                    task_description="detail",
                    dependencies=[1],
                )
            ],
        )
        verdict = check_plan_readiness(plan, registry)
        self.assertTrue(verdict.ready)

    def test_block_independent_step(self) -> None:
        registry = ToolRegistry.from_tools([_OrderTool()])
        plan = ExecutionPlan(
            task_type="general_task",
            steps=[
                ExecutionStep(
                    step_id=1,
                    tool_name="placeOrder",
                    tool_args={},
                    task_description="order",
                    dependencies=[],
                )
            ],
        )
        verdict = check_plan_readiness(plan, registry, task_summary="下单")
        self.assertFalse(verdict.ready)
        self.assertEqual(len(verdict.gaps), 1)
        self.assertIn("宠物 ID", verdict.clarify_message)
        self.assertIn("下单", verdict.clarify_message)

    def test_params_for_user_clarification_openapi_empty_required(self) -> None:
        """OpenAPI required=[] 时仍应提示非可选 body 字段。"""
        params = {
            "type": "object",
            "properties": {
                "gatedCommunityId": {
                    "type": "string",
                    "description": "小区id",
                },
                "productId": {
                    "type": "string",
                    "description": "产品ID",
                },
                "licensePlate": {
                    "type": ["string", "null"],
                    "description": "车牌",
                },
                "parkingSpot": {
                    "type": ["string", "null"],
                    "description": "车位",
                },
                "deviceCode": {
                    "type": ["string", "null"],
                    "description": "指定钥匙柜设备编号（可选）",
                },
            },
            "required": [],
        }
        names = [p[0] for p in params_for_user_clarification(params)]
        self.assertEqual(
            names,
            ["gatedCommunityId", "productId", "licensePlate", "parkingSpot"],
        )
        hints = format_tool_param_hints(params)
        self.assertIn("小区id", hints)
        self.assertIn("产品ID", hints)
        self.assertIn("车牌", hints)
        self.assertIn("车位", hints)
        self.assertNotIn("deviceCode", hints)
        self.assertNotIn("可选", hints)


if __name__ == "__main__":
    unittest.main()
