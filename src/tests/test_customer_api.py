import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.app import app
from src.customer_api import (
    ValidationError,
    _deepseek_analysis,
    assess_risk,
    build_behavior_profile,
    parse_cached_analysis,
    parse_model_analysis,
    risk_label,
    validate_customer_create,
)

VALID_PAYLOAD = {
    "age_group": "35-44",
    "city": "上海",
    "occupation": "企业职员",
    "income_level": "30-50万",
    "register_date": "2026-04-01",
    "aum": 650000,
    "vip_level": "金卡",
    "has_app": True,
}

PROFILE = {
    "basic_info": {
        "customer_id": "C000001",
        "risk_appetite": "R5",
        "risk_label": "进取型",
        "aum": 500000.0,
        "vip_level": "金卡",
    },
    "asset_profile": {
        "holding_amount": 200000.0,
        "holding_product_count": 2,
        "holdings": [{"product_id": "P001"}],
    },
    "behavior_profile": {
        "recent_30d_counts": {"login": 2, "consult": 1, "complaint": 0},
        "tags": ["数字渠道客户"],
    },
}


class RiskAssessmentTestCase(unittest.TestCase):
    def test_balanced_profile_maps_to_r4(self):
        self.assertEqual(
            assess_risk(
                {
                    "age_group": "35-44",
                    "income_level": "30-50万",
                    "occupation": "企业职员",
                    "aum": 650000,
                }
            ),
            "R4",
        )

    def test_conservative_profile_maps_to_r1(self):
        self.assertEqual(
            assess_risk(
                {
                    "age_group": "65+",
                    "income_level": "10万以下",
                    "occupation": "退休",
                    "aum": 50000,
                }
            ),
            "R1",
        )

    def test_risk_labels(self):
        self.assertEqual(risk_label("R1"), "谨慎型")
        self.assertEqual(risk_label("R5"), "进取型")


class CustomerValidationTestCase(unittest.TestCase):
    def test_valid_payload(self):
        payload = validate_customer_create(VALID_PAYLOAD)
        self.assertEqual(payload["aum"], Decimal("650000"))
        self.assertIs(payload["has_app"], True)

    def test_negative_aum_rejected(self):
        with self.assertRaises(ValidationError):
            validate_customer_create({**VALID_PAYLOAD, "aum": -1})

    def test_unknown_age_group_rejected(self):
        with self.assertRaises(ValidationError):
            validate_customer_create({**VALID_PAYLOAD, "age_group": "90-100"})

    def test_future_register_date_rejected(self):
        with self.assertRaises(ValidationError):
            validate_customer_create(
                {**VALID_PAYLOAD, "register_date": "2026-04-16"},
                business_date=date(2026, 4, 15),
            )

    def test_has_app_must_be_boolean(self):
        with self.assertRaises(ValidationError):
            validate_customer_create({**VALID_PAYLOAD, "has_app": 1})


class AiAnalysisTestCase(unittest.TestCase):
    def test_parses_fixed_text_format(self):
        analysis = parse_model_analysis(
            "画像概述：客户具有进取型风险偏好。\n"
            "需求洞察：当前配置体现资金灵活性。\n"
            "服务建议：建议通过线上渠道持续沟通。\n"
            "高亮关键词：进取型风险偏好｜资金灵活性｜线上渠道"
        )
        self.assertEqual(analysis["overview"], "客户具有进取型风险偏好。")
        self.assertEqual(
            analysis["highlights"],
            ["进取型风险偏好", "资金灵活性", "线上渠道"],
        )

    def test_labeled_legacy_cache_is_split_without_line_breaks(self):
        analysis = parse_cached_analysis(
            "画像概述：客户偏好流动性。需求洞察：客户兼顾收益弹性。"
            "服务建议：建议持续线上沟通。"
        )
        self.assertEqual(analysis["overview"], "客户偏好流动性。")
        self.assertEqual(analysis["insight"], "客户兼顾收益弹性。")
        self.assertEqual(analysis["suggestion"], "建议持续线上沟通。")

    def test_plain_legacy_cache_remains_readable(self):
        analysis = parse_cached_analysis("这是一段历史纯文本总结。")
        self.assertEqual(analysis["overview"], "这是一段历史纯文本总结。")
        self.assertEqual(analysis["highlights"], [])

    @patch.dict(
        "os.environ",
        {
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_MODEL": "deepseek-v4-pro",
            "DEEPSEEK_TIMEOUT_SECONDS": "60",
        },
        clear=False,
    )
    @patch("openai.OpenAI")
    def test_deepseek_uses_prompt_format_instead_of_json_output(self, openai_client):
        completion = MagicMock()
        completion.choices = [
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        "画像概述：客户具有进取型风险偏好。\n"
                        "需求洞察：当前配置体现资金灵活性。\n"
                        "服务建议：建议通过线上渠道持续沟通。\n"
                        "高亮关键词：进取型风险偏好｜资金灵活性｜线上渠道"
                    )
                )
            )
        ]
        openai_client.return_value.chat.completions.create.return_value = completion

        analysis, model = _deepseek_analysis(PROFILE)

        self.assertEqual(model, "deepseek-v4-pro")
        self.assertEqual(analysis["suggestion"], "建议通过线上渠道持续沟通。")
        kwargs = openai_client.return_value.chat.completions.create.call_args.kwargs
        self.assertNotIn("response_format", kwargs)
        self.assertIn("四行固定格式", kwargs["messages"][0]["content"])
        self.assertIn("不要返回JSON", kwargs["messages"][0]["content"])
        self.assertNotIn("C000001", kwargs["messages"][1]["content"])


class CustomerProfileAsOfTestCase(unittest.TestCase):
    def test_recent_30d_uses_business_date_as_exclusive_upper_bound(self):
        profile = build_behavior_profile(
            {
                "aum": Decimal("100000"),
                "risk_appetite": "R3",
                "has_app": True,
            },
            [
                {"event_type": "login", "event_date": date(2026, 3, 15)},
                {"event_type": "login", "event_date": date(2026, 3, 16)},
                {"event_type": "consult", "event_date": date(2026, 4, 14)},
                {"event_type": "complaint", "event_date": date(2026, 4, 15)},
            ],
            {"high_liquidity_ratio": 0.0},
            date(2026, 4, 15),
        )

        self.assertEqual(
            profile["recent_30d_counts"],
            {"login": 1, "consult": 1, "complaint": 0},
        )
        self.assertEqual(profile["recent_30d_start"], "2026-03-16")
        self.assertEqual(profile["recent_30d_end_exclusive"], "2026-04-15")
        self.assertEqual(profile["latest_event_date"], "2026-04-14")


class CustomerApiRouteTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("src.customer_api.list_customers")
    def test_list_customers_envelope(self, mock_list):
        mock_list.return_value = {
            "items": [], "total": 0, "page": 1, "page_size": 20,
        }
        response = self.client.get("/api/v1/customers")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["total"], 0)

    @patch("src.customer_api.create_customer")
    def test_create_customer_envelope(self, mock_create):
        mock_create.return_value = {"customer_id": "C1", "risk_appetite": "R3"}
        response = self.client.post(
            "/api/v1/customers?business_date=2026-04-15", json={"demo": True}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["data"]["customer_id"], "C1")
        self.assertEqual(mock_create.call_args.args[1], date(2026, 4, 15))

    @patch("src.customer_api.create_customer")
    def test_create_customer_rejects_historical_snapshot(self, mock_create):
        response = self.client.post(
            "/api/v1/customers?business_date=2026-01-30", json={"demo": True}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("只读快照", response.get_json()["message"])
        mock_create.assert_not_called()

    def test_list_customers_invalid_page(self):
        response = self.client.get("/api/v1/customers?page=0")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], 400)


if __name__ == "__main__":
    unittest.main()
