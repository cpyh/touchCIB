import unittest
from types import SimpleNamespace

import pandas as pd

from src.partA1serving.training.predict import generate


class _FakePredictor:
    meta = SimpleNamespace(prior=0.2)

    def __init__(self) -> None:
        self.requests = []

    def predict_batch(self, requests, *, explain=False):
        self.requests.extend(requests)
        return [
            SimpleNamespace(probability=0.8 if request.product_id == "P002" else 0.2)
            for request in requests
        ]


class A1SubmissionPredictTestCase(unittest.TestCase):
    def test_export_uses_injected_serving_predictor_and_keeps_contact_order(self):
        contacts = pd.DataFrame(
            [
                {
                    "contact_id": "KT2",
                    "customer_id": "C2",
                    "product_id": "P002",
                    "channel": "manager",
                    "contact_date": "2026-04-15",
                },
                {
                    "contact_id": "KT1",
                    "customer_id": "C1",
                    "product_id": "P001",
                    "channel": "sms",
                    "contact_date": "2026-04-15",
                },
            ]
        )
        predictor = _FakePredictor()

        output = generate(
            verbose=False,
            model="lgbm_onehot",
            predictor=predictor,
            test_contacts=contacts,
            batch_size=1,
        )

        self.assertEqual(output["contact_id"].tolist(), ["KT2", "KT1"])
        self.assertEqual(output["response_prob"].tolist(), [0.8, 0.2])
        self.assertEqual(len(predictor.requests), 2)

    def test_export_rejects_duplicate_contact_id(self):
        contacts = pd.DataFrame(
            [
                {
                    "contact_id": "KT1",
                    "customer_id": "C1",
                    "product_id": "P001",
                    "channel": "sms",
                    "contact_date": "2026-04-15",
                },
                {
                    "contact_id": "KT1",
                    "customer_id": "C2",
                    "product_id": "P002",
                    "channel": "call",
                    "contact_date": "2026-04-15",
                },
            ]
        )
        with self.assertRaisesRegex(ValueError, "重复 contact_id"):
            generate(
                verbose=False,
                predictor=_FakePredictor(),
                test_contacts=contacts,
            )


if __name__ == "__main__":
    unittest.main()

