import unittest
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

from src.algorithms.partb import (
    build_covariance_matrix,
    build_masks,
    load_correlation_matrix,
    load_products,
    read_dict_csv,
)
from src.app import app
from src.portfolio import _ai_prompt, _portfolio_chat_system_prompt


DATA_DIR = Path(__file__).resolve().parents[2] / "src" / "data" / "raw"


PORTFOLIO_CHAT_CONTEXT = {
    "context_version": "portfolio_comparison_v1",
    "business_date": "2025-05-31",
    "customer": {"customer_id": "C000001", "risk_appetite": "R3", "aum": 500000},
    "current_portfolio": {
        "holding_amount": 300000,
        "holdings": [
            {
                "product_id": "P001",
                "product_name": "现有稳健产品",
                "amount": 300000,
            }
        ],
    },
    "optimization_result": {
        "theoretical": {"summary": {"expected_return": 0.06}},
        "executable": {
            "expected_return": 0.055,
            "allocations": [
                {
                    "product_id": "P002",
                    "product_name": "目标配置产品",
                    "amount": 250000,
                }
            ],
        },
    },
    "rebalance_candidates": {
        "buys": [{"product_id": "P002", "amount": 250000}],
        "sells": [{"product_id": "P001", "amount": 300000}],
    },
}


@lru_cache(maxsize=1)
def csv_optimizer_context():
    products = load_products(DATA_DIR)
    correlation = load_correlation_matrix(DATA_DIR, products.product_ids)
    covariance = build_covariance_matrix(products.volatility, correlation)
    high_risk_mask, non_liquid_mask = build_masks(products)
    details = {
        row["product_id"]: row for row in read_dict_csv(DATA_DIR / "t_product.csv")
    }
    return products, covariance, high_risk_mask, non_liquid_mask, details


class PortfolioEndpointTestCase(unittest.TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.context_patch = patch(
            "src.portfolio.optimizer_context",
            return_value=csv_optimizer_context(),
        )
        self.context_patch.start()

    def tearDown(self) -> None:
        self.context_patch.stop()

    def test_optimize_one_scenario(self) -> None:
        response = self.client.post(
            "/portfolio/optimize",
            json={
                "total_amount": 500000,
                "risk_aversion": 0.94,
                "max_single_weight": 0.3,
                "max_high_risk_weight": 0.5,
                "min_liquid_weight": 0.2,
                "min_holdings": 4,
            },
        )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertGreaterEqual(result["summary"]["holdings_count"], 4)
        self.assertLessEqual(result["summary"]["invested_weight"], 1.000001)
        self.assertEqual(
            len(result["allocations"]),
            result["summary"]["holdings_count"],
        )
        self.assertGreater(len(result["allocations"]), 0)

    def test_rejects_invalid_min_holdings(self) -> None:
        response = self.client.post(
            "/portfolio/optimize",
            json={
                "total_amount": 500000,
                "risk_aversion": 0.94,
                "max_single_weight": 0.3,
                "max_high_risk_weight": 0.5,
                "min_liquid_weight": 0.2,
                "min_holdings": 31,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("min_holdings", response.get_json()["error"])

    @patch(
        "src.algorithms.solve_partB_business_pipeline_fullswap.solve_business_scenario"
    )
    def test_theory_only_skips_business_solver(self, mock_business_solver) -> None:
        response = self.client.post(
            "/portfolio/optimize",
            json={
                "total_amount": 500000,
                "risk_aversion": 0.94,
                "max_single_weight": 0.3,
                "max_high_risk_weight": 0.5,
                "min_liquid_weight": 0.2,
                "min_holdings": 4,
                "include_business": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["business"])
        mock_business_solver.assert_not_called()

    def test_rejects_invalid_include_business(self) -> None:
        response = self.client.post(
            "/portfolio/optimize",
            json={
                "total_amount": 500000,
                "risk_aversion": 0.94,
                "max_single_weight": 0.3,
                "max_high_risk_weight": 0.5,
                "min_liquid_weight": 0.2,
                "min_holdings": 4,
                "include_business": "no",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("include_business", response.get_json()["error"])


class PortfolioPromptTestCase(unittest.TestCase):
    def test_chat_prompt_uses_current_holdings_as_comparison_baseline(self) -> None:
        prompt = _portfolio_chat_system_prompt(PORTFOLIO_CHAT_CONTEXT)

        self.assertIn("以客户现有持仓为基线", prompt)
        self.assertIn("不要把任务理解为重新判断求解器", prompt)
        self.assertIn("投顾分析报告，不是营销触达方案", prompt)
        self.assertIn("业务可执行组合", prompt)
        self.assertIn("按 product_id 对齐", prompt)
        self.assertIn("投顾结论｜", prompt)
        self.assertIn("现有组合诊断｜", prompt)
        self.assertIn("配置依据｜", prompt)
        self.assertIn("风险收益变化｜", prompt)
        self.assertIn("除非用户明确要求生成客户解释版本", prompt)
        self.assertIn("现有稳健产品", prompt)
        self.assertIn("目标配置产品", prompt)

    def test_single_turn_prompt_reuses_comparison_semantics(self) -> None:
        prompt = _ai_prompt(PORTFOLIO_CHAT_CONTEXT)

        self.assertIn("current_portfolio 是业务日期下的真实现有持仓", prompt)
        self.assertIn("请完成首次对比分析", prompt)


if __name__ == "__main__":
    unittest.main()
