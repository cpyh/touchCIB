import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.partA1serving.predictor import ResponsePredictor


class _FakePreprocessor:
    def transform(self, _frame):
        return np.asarray([[1.0, 2.0]])

    def get_feature_names_out(self):
        return np.asarray(["channel_manager", "abs_risk_gap"])


class _FakeBooster:
    def predict(self, _frame, pred_contrib=False):
        assert pred_contrib
        # 两个局部 TreeSHAP 贡献 + 一列 expected value。
        return np.asarray([[0.8, -0.35, -1.1]])


class A1LocalExplanationTestCase(unittest.TestCase):
    def test_tree_model_returns_customer_level_factors(self):
        predictor = ResponsePredictor.__new__(ResponsePredictor)
        pre = _FakePreprocessor()
        predictor.pipeline = SimpleNamespace(
            named_steps={"pre": pre, "clf": SimpleNamespace(booster_=_FakeBooster())},
            steps=[("pre", pre), ("clf", object())],
        )
        predictor.meta = SimpleNamespace(
            feature_columns=["channel", "abs_risk_gap"]
        )

        factors, method = predictor._explain_factors(
            pd.DataFrame([{"channel": "manager", "abs_risk_gap": 1}])
        )

        self.assertEqual(method, "tree_shap")
        self.assertEqual(factors[0].label, "触达渠道 · manager")
        self.assertEqual(factors[0].direction, "positive")
        self.assertEqual(factors[1].label, "风险等级匹配度")
        self.assertEqual(factors[1].direction, "negative")
        self.assertTrue(all("局部贡献" in factor.reason for factor in factors))


if __name__ == "__main__":
    unittest.main()
