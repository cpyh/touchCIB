import unittest
from datetime import date

from src.marketing.models import (
    Customer,
    CustomerBehavior,
    Product,
    StrategyRequest,
)
from src.marketing.pipeline import generate_strategies
from src.marketing.templates import COMPLIANCE_NOTE, OVERSHOOT_NOTE
from src.marketing.validate import validate_strategy_rows

AS_OF = date(2026, 3, 31)


def make_customer(customer_id="C1", **overrides):
    defaults = dict(
        customer_id=customer_id,
        age_group="35-44",
        city="上海",
        occupation="企业职员",
        income_level="10-30万",
        register_date=date(2024, 1, 1),
        aum=100_000.0,
        risk_appetite="R3",
        vip_level="普通",
        has_app=True,
    )
    defaults.update(overrides)
    return Customer(**defaults)


def make_product(product_id, risk_level="R2", **overrides):
    defaults = dict(
        product_id=product_id,
        product_name=f"产品{product_id}",
        product_type="混合",
        risk_level=risk_level,
        expected_return=0.05,
        volatility=0.1,
        min_invest=10_000.0,
        duration_days=0,
        liquidity="T+0",
        launch_date=date(2025, 1, 1),
    )
    defaults.update(overrides)
    return Product(**defaults)


def make_products():
    return [
        make_product("P01", "R1"),
        make_product("P02", "R1"),
        make_product("P03", "R2"),
        make_product("P04", "R2"),
        make_product("P05", "R3"),
        make_product("P06", "R4"),
        make_product("P07", "R5"),
    ]


def make_behavior(customer_id="C1", **overrides):
    defaults = dict(customer_id=customer_id)
    defaults.update(overrides)
    return CustomerBehavior(**defaults)


class MarketingPipelineTestCase(unittest.TestCase):
    def run_pipeline(self, requests, **kwargs):
        return generate_strategies(
            requests, make_products(), **kwargs
        )

    def test_r1_customer_overshoot_fills_three_rows(self):
        customer = make_customer("CR1", risk_appetite="R1")
        request = StrategyRequest(
            customer=customer,
            strategy_date=AS_OF,
            behavior=make_behavior("CR1"),
        )
        (result,) = self.run_pipeline([request])
        self.assertEqual(len(result.items), 3)
        # 2 个偏好内（R1）+ 1 个溢出（R2）
        overshoot_items = [item for item in result.items if item.overshoot]
        self.assertEqual(len(overshoot_items), 1)
        self.assertTrue(
            all(OVERSHOOT_NOTE in item.marketing_script for item in overshoot_items)
        )
        # 溢出产品必须是 R2
        product_risk = {p.product_id: p.risk_level for p in make_products()}
        self.assertEqual(
            product_risk[overshoot_items[0].product_id], "R2"
        )
        errors = validate_strategy_rows(result.to_rows())
        self.assertEqual(errors, [])

    def test_all_items_pass_compliance_and_enums(self):
        for risk in ("R1", "R2", "R3", "R4", "R5"):
            customer = make_customer(f"C{risk}", risk_appetite=risk)
            request = StrategyRequest(
                customer=customer,
                strategy_date=AS_OF,
                behavior=make_behavior(customer.customer_id),
            )
            (result,) = self.run_pipeline([request])
            self.assertEqual(len(result.items), 3, risk)
            for item in result.items:
                self.assertIn(item.recommended_channel,
                              ("sms", "call", "app_push", "manager"))
                self.assertIn(
                    item.recommended_time,
                    (
                        "工作日09:00-12:00", "工作日12:00-14:00",
                        "工作日18:00-21:00", "周末09:00-12:00",
                        "周末14:00-18:00",
                    ),
                )
                self.assertTrue(10 <= len(item.marketing_script) <= 300)
                self.assertIn(COMPLIANCE_NOTE, item.marketing_script)

    def test_no_app_customer_never_gets_app_push(self):
        customer = make_customer("CNOAPP", has_app=False)
        request = StrategyRequest(
            customer=customer,
            strategy_date=AS_OF,
            behavior=make_behavior("CNOAPP"),
        )
        (result,) = self.run_pipeline([request])
        self.assertTrue(result.items)
        self.assertTrue(
            all(item.recommended_channel != "app_push" for item in result.items)
        )

    def test_complaint_customer_never_gets_call(self):
        customer = make_customer("CCPL", has_app=False)  # 只剩 call/sms 时禁 call
        request = StrategyRequest(
            customer=customer,
            strategy_date=AS_OF,
            behavior=make_behavior("CCPL", complaint_count_90d=3),
        )
        (result,) = self.run_pipeline([request])
        self.assertTrue(
            all(item.recommended_channel != "call" for item in result.items)
        )

    def test_manager_pool_only_contains_eligible_customers(self):
        customers = [
            make_customer("CVIP1", vip_level="金卡", aum=600_000.0),
            make_customer("CVIP2", vip_level="钻石", aum=300_000.0),
            make_customer("CPLN", vip_level="普通", aum=900_000.0),
            make_customer("CORD", vip_level="普通", aum=50_000.0),
        ]
        requests = [
            StrategyRequest(
                customer=customer,
                strategy_date=AS_OF,
                behavior=make_behavior(customer.customer_id),
            )
            for customer in customers
        ]
        results = self.run_pipeline(requests, manager_pool_size=3)
        manager_customers = {
            result.customer_id
            for result in results
            for item in result.items
            if item.recommended_channel == "manager"
        }
        self.assertEqual(manager_customers, {"CVIP1", "CVIP2", "CPLN"})

    def test_manager_pool_size_limits_customers_not_strategy_rows(self):
        customers = [
            make_customer(f"CV{i:03d}", vip_level="金卡", aum=float(i))
            for i in range(5)
        ]
        requests = [
            StrategyRequest(
                customer=customer,
                strategy_date=AS_OF,
                behavior=make_behavior(customer.customer_id),
            )
            for customer in customers
        ]
        results = self.run_pipeline(requests, manager_pool_size=2)
        manager_rows = sum(
            1
            for result in results
            for item in result.items
            if item.recommended_channel == "manager"
        )
        self.assertEqual(manager_rows, 6)

    def test_model_scores_drive_ranking(self):
        customer = make_customer("CMODEL", risk_appetite="R3")
        request = StrategyRequest(
            customer=customer,
            strategy_date=AS_OF,
            behavior=make_behavior("CMODEL"),
        )
        model_scores = {
            ("CMODEL", "P05"): 0.9,
            ("CMODEL", "P01"): 0.1,
            ("CMODEL", "P02"): 0.2,
        }
        (result,) = self.run_pipeline([request], model_scores=model_scores)
        self.assertEqual(result.items[0].product_id, "P05")

    def test_deterministic_across_runs(self):
        customers = [
            make_customer("CD1", risk_appetite="R2", vip_level="金卡"),
            make_customer("CD2", risk_appetite="R4", has_app=False),
        ]
        requests = [
            StrategyRequest(
                customer=customer,
                strategy_date=AS_OF,
                behavior=make_behavior(customer.customer_id),
            )
            for customer in customers
        ]
        first = self.run_pipeline(requests, manager_quota=2)
        second = self.run_pipeline(requests, manager_quota=2)
        self.assertEqual(
            [result.to_rows() for result in first],
            [result.to_rows() for result in second],
        )

    def test_steps_recorded_for_dashboard(self):
        customer = make_customer("CSTEPS", risk_appetite="R1")
        request = StrategyRequest(
            customer=customer,
            strategy_date=AS_OF,
            behavior=make_behavior("CSTEPS"),
        )
        (result,) = self.run_pipeline([request])
        step_names = [step.step for step in result.steps]
        self.assertEqual(
            step_names,
            [
                "compliance_filter",
                "ranking",
                "channel_selection",
                "slot_selection",
                "script_generation",
                "validation",
            ],
        )
        self.assertIn("溢出", result.steps[0].summary)


if __name__ == "__main__":
    unittest.main()
