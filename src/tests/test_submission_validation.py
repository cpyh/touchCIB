import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.scripts.check_submission import validate_prediction_file


class SubmissionValidationTestCase(unittest.TestCase):
    def test_prediction_validator_accepts_exact_coverage(self) -> None:
        expected = pd.DataFrame({"contact_id": ["KT1", "KT2"]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prediction.csv"
            pd.DataFrame(
                {
                    "contact_id": ["KT1", "KT2"],
                    "response_prob": [0.1, 0.9],
                }
            ).to_csv(path, index=False)

            validate_prediction_file(path, expected)

    def test_prediction_validator_rejects_duplicate_ids(self) -> None:
        expected = pd.DataFrame({"contact_id": ["KT1", "KT2"]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prediction.csv"
            pd.DataFrame(
                {
                    "contact_id": ["KT1", "KT1"],
                    "response_prob": [0.1, 0.9],
                }
            ).to_csv(path, index=False)

            with self.assertRaisesRegex(ValueError, "duplicate"):
                validate_prediction_file(path, expected)


if __name__ == "__main__":
    unittest.main()
