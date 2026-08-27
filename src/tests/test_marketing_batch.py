import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from src.marketing.batch import allocate_manager_customers, compute_marketing_batch
from src.marketing.models import Customer, CustomerBehavior, Product
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


class MarketingBatchTestCase(unittest.TestCase):
    def test_manager_quota_is_allocated_in_complete_top3_units(self):
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

        allocated = allocate_manager_customers(customers, manager_quota=6)

        self.assertEqual(allocated, {"C1", "C2"})

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


if __name__ == "__main__":
    unittest.main()
