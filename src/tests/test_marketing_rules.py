import unittest
from datetime import date, timedelta

from src.marketing.engine import RuleEngine
from src.marketing.models import Customer, CustomerBehavior, Product
from src.marketing.rules import build_default_engine
from src.marketing.templates import COMPLIANCE_NOTE, OVERSHOOT_NOTE


def make_customer(**overrides):
    defaults = dict(
        customer_id="C1",
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


def make_product(**overrides):
    defaults = dict(
        product_id="P001",
        product_name="测试产品",
        product_type="混合",
        risk_level="R2",
        expected_return=0.05,
        volatility=0.1,
        min_invest=10_000.0,
        duration_days=0,
        liquidity="T+0",
        launch_date=date(2025, 1, 1),
    )
    defaults.update(overrides)
    return Product(**defaults)


def behavior(**overrides):
    defaults = dict(
        customer_id="C1",
        holding_product_ids=(),
        complaint_count_90d=0,
        consult_count_90d=0,
        login_count_30d=0,
    )
    defaults.update(overrides)
    return CustomerBehavior(**defaults)


class MarketingRulesTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = build_default_engine()
        self.date = date(2026, 3, 31)

    def base_context(self, **overrides):
        context = {
            "customer": make_customer(),
            "product": make_product(),
            "strategy_date": self.date,
        }
        context.update(overrides)
        return context

    def test_catalog_has_14_rules_with_unique_ids(self):
        metadata = self.engine.metadata()
        self.assertEqual(len(metadata), 14)
        ids = [entry["rule_id"] for entry in metadata]
        self.assertEqual(len(ids), len(set(ids)))

    def test_risk_match_pass_fail_overshoot(self):
        ok = self.engine.evaluate(
            "risk_match",
            self.base_context(customer=make_customer(risk_appetite="R3"),
                              product=make_product(risk_level="R2")),
        )
        self.assertTrue(ok.passed)

        fail = self.engine.evaluate(
            "risk_match",
            self.base_context(customer=make_customer(risk_appetite="R2"),
                              product=make_product(risk_level="R3")),
        )
        self.assertFalse(fail.passed)

        overshoot = self.engine.evaluate(
            "risk_match",
            self.base_context(
                customer=make_customer(risk_appetite="R1"),
                product=make_product(risk_level="R2"),
                max_allowed_risk=2,
            ),
        )
        self.assertTrue(overshoot.passed)
        self.assertIn("溢出", overshoot.reason)

    def test_product_launched_as_of(self):
        ok = self.engine.evaluate(
            "product_launched",
            self.base_context(product=make_product(launch_date=date(2025, 1, 1))),
        )
        self.assertTrue(ok.passed)
        fail = self.engine.evaluate(
            "product_launched",
            self.base_context(product=make_product(launch_date=date(2026, 6, 1))),
        )
        self.assertFalse(fail.passed)

    def test_customer_registered_as_of(self):
        fail = self.engine.evaluate(
            "customer_registered",
            self.base_context(customer=make_customer(register_date=date(2026, 6, 1))),
        )
        self.assertFalse(fail.passed)

    def test_duration_record_only(self):
        expired = self.engine.evaluate(
            "duration_valid",
            self.base_context(
                product=make_product(launch_date=date(2024, 1, 1), duration_days=30)
            ),
        )
        self.assertTrue(expired.passed)
        self.assertIn("记录", expired.reason)

        open_ended = self.engine.evaluate(
            "duration_valid",
            self.base_context(product=make_product(duration_days=0)),
        )
        self.assertTrue(open_ended.passed)

    def test_min_invest_record_only(self):
        outcome = self.engine.evaluate(
            "min_invest_affordable",
            self.base_context(
                invest_budget=5_000.0, product=make_product(min_invest=10_000.0)
            ),
        )
        self.assertTrue(outcome.passed)
        self.assertIn("记录", outcome.reason)

    def test_aum_constraint_can_be_disabled_for_preview(self):
        context = self.base_context(
            customer=make_customer(aum=5_000.0),
            product=make_product(min_invest=10_000.0),
        )
        blocked = self.engine.evaluate("aum_affordability", context)
        self.assertFalse(blocked.passed)

        preview = self.engine.evaluate(
            "aum_affordability",
            {**context, "disabled_constraints": {"aum_affordability"}},
        )
        self.assertTrue(preview.passed)
        self.assertIn("试算已关闭", preview.reason)

    def test_app_push_requires_app(self):
        fail = self.engine.evaluate(
            "channel_app_requires_app",
            self.base_context(
                customer=make_customer(has_app=False), channel="app_push"
            ),
        )
        self.assertFalse(fail.passed)
        ok = self.engine.evaluate(
            "channel_app_requires_app",
            self.base_context(customer=make_customer(has_app=True),
                              channel="app_push"),
        )
        self.assertTrue(ok.passed)

        preview = self.engine.evaluate(
            "channel_app_requires_app",
            self.base_context(
                customer=make_customer(has_app=False),
                channel="app_push",
                disabled_constraints={"channel_app_requires_app"},
            ),
        )
        self.assertTrue(preview.passed)
        self.assertIn("试算已关闭", preview.reason)

    def test_call_blocked_by_complaints(self):
        fail = self.engine.evaluate(
            "channel_call_complaint_block",
            self.base_context(
                behavior=behavior(complaint_count_90d=2), channel="call"
            ),
        )
        self.assertFalse(fail.passed)
        ok = self.engine.evaluate(
            "channel_call_complaint_block",
            self.base_context(
                behavior=behavior(complaint_count_90d=1), channel="call"
            ),
        )
        self.assertTrue(ok.passed)

        preview = self.engine.evaluate(
            "channel_call_complaint_block",
            self.base_context(
                behavior=behavior(complaint_count_90d=3),
                channel="call",
                disabled_constraints={"channel_call_complaint_block"},
            ),
        )
        self.assertTrue(preview.passed)
        self.assertIn("试算已关闭", preview.reason)

    def test_manager_quota_rule(self):
        unrestricted = self.engine.evaluate(
            "channel_manager_quota",
            self.base_context(channel="manager", manager_allowed=False),
        )
        self.assertTrue(unrestricted.passed)
        self.assertIn("不设全局配额", unrestricted.reason)
        ok = self.engine.evaluate(
            "channel_manager_quota",
            self.base_context(channel="manager", manager_allowed=True),
        )
        self.assertTrue(ok.passed)

    def test_slot_enum(self):
        fail = self.engine.evaluate(
            "slot_in_enum",
            self.base_context(recommended_time="非法时段"),
        )
        self.assertFalse(fail.passed)
        ok = self.engine.evaluate(
            "slot_in_enum",
            self.base_context(recommended_time="周末14:00-18:00"),
        )
        self.assertTrue(ok.passed)

    def test_script_length_boundaries(self):
        fail_short = self.engine.evaluate(
            "script_length", self.base_context(marketing_script="123456789")
        )
        self.assertFalse(fail_short.passed)
        fail_long = self.engine.evaluate(
            "script_length", self.base_context(marketing_script="长" * 301)
        )
        self.assertFalse(fail_long.passed)
        ok = self.engine.evaluate(
            "script_length", self.base_context(marketing_script="合规话术" * 3)
        )
        self.assertTrue(ok.passed)

    def test_script_compliance_note(self):
        fail = self.engine.evaluate(
            "script_compliance_note",
            self.base_context(marketing_script="缺少提示语的话术内容"),
        )
        self.assertFalse(fail.passed)
        ok = self.engine.evaluate(
            "script_compliance_note",
            self.base_context(marketing_script=f"推荐产品。{COMPLIANCE_NOTE}"),
        )
        self.assertTrue(ok.passed)

    def test_script_overshoot_warning(self):
        fail = self.engine.evaluate(
            "script_overshoot_warning",
            self.base_context(
                marketing_script=f"溢出产品。{COMPLIANCE_NOTE}", overshoot=True
            ),
        )
        self.assertFalse(fail.passed)
        ok = self.engine.evaluate(
            "script_overshoot_warning",
            self.base_context(
                marketing_script=f"溢出产品。{OVERSHOOT_NOTE}{COMPLIANCE_NOTE}",
                overshoot=True,
            ),
        )
        self.assertTrue(ok.passed)


if __name__ == "__main__":
    unittest.main()
