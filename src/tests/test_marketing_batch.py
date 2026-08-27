import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from src.marketing.batch import allocate_manager_customers, compute_marketing_batch
from src.marketing.models import Customer, CustomerBehavior, Product
from src.marketing.templates import OVERSHOOT_NOTE
from src.marketing.warehouse import MarketingWarehouseContext, load_marketing_context


class _FakePredictor:
    profile = "full"
    model_name = "fake_a1"
    meta = SimpleNamespace(
        profile="full",
        model_name="fake_a1",
        trained_at="2026-08-27T00:00:00",
        schema_version=3,
    )

    probabilities = {"P001": 0.70, "P002": 0.90, "P003": 0.80, "P004": 0.99}

    def predict_batch(self, requests, *, explain=False):
        self.last_explain = explain
        return [
            SimpleNamespace(
                customer_id=request.customer_id,
                product_id=request.product_id,
                probability=self.probabilities[request.product_id],
            )
            for request in requests
        ]


class _ChannelAwarePredictor(_FakePredictor):
    def __init__(self):
        self.requests = []

    def predict_batch(self, requests, *, explain=False):
        self.requests.extend(requests)
        probabilities = {
            ("P001", "sms"): 0.40,
            ("P001", "call"): 0.90,
            ("P001", "app_push"): 0.95,
            ("P001", "manager"): 0.20,
            ("P002", "sms"): 0.80,
            ("P002", "call"): 0.30,
            ("P002", "app_push"): 0.85,
            ("P002", "manager"): 0.10,
            ("P003", "sms"): 0.70,
            ("P003", "call"): 0.60,
            ("P003", "app_push"): 0.75,
            ("P003", "manager"): 0.20,
        }
        return [
            SimpleNamespace(
                customer_id=request.customer_id,
                product_id=request.product_id,
                channel=request.channel,
                probability=probabilities[(request.product_id, request.channel)],
            )
            for request in requests
        ]


class MarketingBatchTestCase(unittest.TestCase):
    def test_manager_is_open_to_all_customers_and_quota_is_ignored(self):
        customers = [
            Customer(
                customer_id=f"C{index}",
                age_group="35-44",
                city="上海",
                occupation="企业职员",
                income_level="30-50万",
                register_date=date(2024, 1, 1),
                aum=500_000 + index,
                risk_appetite="R2",
                vip_level="金卡",
                has_app=True,
            )
            for index in range(3)
        ]

        allocated = allocate_manager_customers(customers, manager_quota=0)

        self.assertEqual(allocated, {"C0", "C1", "C2"})

    def test_context_excludes_customers_registered_after_strategy_date(self):
        eligible = Customer(
            customer_id="C000001",
            age_group="35-44",
            city="上海",
            occupation="企业职员",
            income_level="30-50万",
            register_date=date(2024, 1, 1),
            aum=200_000,
            risk_appetite="R2",
            vip_level="金卡",
            has_app=True,
        )
        future = Customer(
            customer_id="C_FUTURE",
            age_group="35-44",
            city="上海",
            occupation="企业职员",
            income_level="30-50万",
            register_date=date(2026, 8, 27),
            aum=200_000,
            risk_appetite="R2",
            vip_level="金卡",
            has_app=True,
        )
        source = SimpleNamespace(
            load=lambda: SimpleNamespace(
                customers=None,
                products=None,
                events=SimpleNamespace(copy=lambda: None),
                holdings=SimpleNamespace(copy=lambda: None),
            )
        )

        with (
            patch(
                "src.marketing.warehouse._customers",
                return_value={
                    eligible.customer_id: eligible,
                    future.customer_id: future,
                },
            ),
            patch("src.marketing.warehouse._products", return_value=()),
            patch(
                "src.marketing.warehouse.build_behaviors",
                return_value={eligible.customer_id: CustomerBehavior(eligible.customer_id)},
            ),
        ):
            context = load_marketing_context(
                date(2026, 4, 15), data_source=source
            )

            self.assertEqual(list(context.customers), [eligible.customer_id])
            with self.assertRaisesRegex(ValueError, "尚未注册"):
                load_marketing_context(
                    date(2026, 4, 15),
                    customer_ids=[future.customer_id],
                    data_source=source,
                )

    def test_a1_rank_then_rules_filter_to_top3(self):
        customer = Customer(
            customer_id="C000001",
            age_group="35-44",
            city="上海",
            occupation="企业职员",
            income_level="30-50万",
            register_date=date(2024, 1, 1),
            aum=200_000,
            risk_appetite="R2",
            vip_level="金卡",
            has_app=True,
        )
        products = tuple(
            Product(
                product_id=f"P00{index}",
                product_name=f"产品{index}",
                product_type="混合",
                risk_level="R5" if index == 4 else "R2",
                expected_return=0.03 + index / 100,
                volatility=0.02,
                min_invest=10_000,
                duration_days=90,
                liquidity="T+1",
                launch_date=date(2025, 1, 1),
            )
            for index in range(1, 5)
        )
        context = MarketingWarehouseContext(
            customers={customer.customer_id: customer},
            products=products,
            behaviors={customer.customer_id: CustomerBehavior(customer.customer_id)},
            strategy_date=date(2026, 4, 15),
        )
        predictor = _FakePredictor()

        result = compute_marketing_batch(context, predictor, batch_id="test_batch")

        self.assertFalse(predictor.last_explain)
        self.assertEqual(len(result.score_rows), 4)
        decisions = {row[2]: row for row in result.decision_rows}
        self.assertEqual(decisions["P004"][3], 1)
        self.assertEqual(decisions["P004"][6], 0)
        self.assertIn("超出客户风险偏好", decisions["P004"][8])
        top3 = [row[4] for row in result.strategy_rows]
        self.assertEqual(top3, ["P002", "P003", "P001"])
        self.assertEqual([row[9] for row in result.strategy_rows], [2, 3, 4])
        trace = json.loads(result.strategy_rows[0][10])
        self.assertTrue(all(rule["passed"] for rule in trace))

    def test_one_level_risk_overshoot_competes_in_probability_top3(self):
        customer = Customer(
            customer_id="C000001",
            age_group="35-44",
            city="上海",
            occupation="企业职员",
            income_level="30-50万",
            register_date=date(2024, 1, 1),
            aum=200_000,
            risk_appetite="R2",
            vip_level="金卡",
            has_app=True,
        )
        products = tuple(
            Product(
                product_id=f"P00{index}",
                product_name=f"产品{index}",
                product_type="混合",
                risk_level="R3" if index == 4 else "R2",
                expected_return=0.03 + index / 100,
                volatility=0.02,
                min_invest=10_000,
                duration_days=90,
                liquidity="T+1",
                launch_date=date(2025, 1, 1),
            )
            for index in range(1, 5)
        )
        context = MarketingWarehouseContext(
            customers={customer.customer_id: customer},
            products=products,
            behaviors={customer.customer_id: CustomerBehavior(customer.customer_id)},
            strategy_date=date(2026, 4, 15),
        )

        result = compute_marketing_batch(
            context, _FakePredictor(), batch_id="risk_plus_one"
        )

        self.assertEqual(
            [row[4] for row in result.strategy_rows],
            ["P004", "P002", "P003"],
        )
        overshoot_row = result.strategy_rows[0]
        self.assertIn(OVERSHOOT_NOTE, overshoot_row[7])
        risk_rule = next(
            rule
            for rule in json.loads(overshoot_row[10])
            if rule["rule_id"] == "risk_match"
        )
        self.assertTrue(risk_rule["passed"])

    def test_product_ranking_keeps_best_executable_channel(self):
        customer = Customer(
            customer_id="C000001",
            age_group="35-44",
            city="上海",
            occupation="企业职员",
            income_level="30-50万",
            register_date=date(2024, 1, 1),
            aum=200_000,
            risk_appetite="R2",
            vip_level="普通",
            has_app=False,
        )
        products = tuple(
            Product(
                product_id=f"P00{index}",
                product_name=f"产品{index}",
                product_type="混合",
                risk_level="R2",
                expected_return=0.03,
                volatility=0.02,
                min_invest=10_000,
                duration_days=90,
                liquidity="T+1",
                launch_date=date(2025, 1, 1),
            )
            for index in range(1, 4)
        )
        context = MarketingWarehouseContext(
            customers={customer.customer_id: customer},
            products=products,
            behaviors={customer.customer_id: CustomerBehavior(customer.customer_id)},
            strategy_date=date(2026, 4, 15),
        )
        predictor = _ChannelAwarePredictor()

        result = compute_marketing_batch(context, predictor, batch_id="channel_grid")

        self.assertEqual(
            {request.channel for request in predictor.requests},
            {"sms", "call", "manager"},
        )
        self.assertEqual(len(predictor.requests), 9)
        score_channels = {row[2]: row[3] for row in result.score_rows}
        self.assertEqual(score_channels["P001"], "call")
        self.assertEqual(score_channels["P002"], "sms")
        self.assertEqual(
            [(row[4], row[5]) for row in result.strategy_rows],
            [("P001", "call"), ("P002", "sms"), ("P003", "sms")],
        )

    def test_disabling_app_constraint_allows_app_push_into_top3(self):
        customer = Customer(
            customer_id="C000001",
            age_group="35-44",
            city="上海",
            occupation="企业职员",
            income_level="30-50万",
            register_date=date(2024, 1, 1),
            aum=200_000,
            risk_appetite="R2",
            vip_level="普通",
            has_app=False,
        )
        products = tuple(
            Product(
                product_id=f"P00{index}",
                product_name=f"产品{index}",
                product_type="混合",
                risk_level="R2",
                expected_return=0.03,
                volatility=0.02,
                min_invest=10_000,
                duration_days=90,
                liquidity="T+1",
                launch_date=date(2025, 1, 1),
            )
            for index in range(1, 4)
        )
        context = MarketingWarehouseContext(
            customers={customer.customer_id: customer},
            products=products,
            behaviors={customer.customer_id: CustomerBehavior(customer.customer_id)},
            strategy_date=date(2026, 4, 15),
        )
        predictor = _ChannelAwarePredictor()

        result = compute_marketing_batch(
            context,
            predictor,
            batch_id="app_constraint_off",
            disabled_constraints=("channel_app_requires_app",),
        )

        self.assertEqual(
            {request.channel for request in predictor.requests},
            {"sms", "call", "app_push", "manager"},
        )
        self.assertEqual(
            [row[5] for row in result.strategy_rows],
            ["app_push", "app_push", "app_push"],
        )
        traces = [json.loads(row[10]) for row in result.strategy_rows]
        app_rules = [
            next(rule for rule in trace if rule["rule_id"] == "channel_app_requires_app")
            for trace in traces
        ]
        self.assertTrue(all(rule["passed"] for rule in app_rules))
        self.assertTrue(all("试算已关闭" in rule["reason"] for rule in app_rules))


if __name__ == "__main__":
    unittest.main()
