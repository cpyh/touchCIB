import unittest
from datetime import date

import pandas as pd

from src.marketing.collaborative import (
    build_co_holding_similarity,
    customer_cf_scores,
)


class CollaborativeFilteringTestCase(unittest.TestCase):
    def setUp(self):
        # c1: P1, P2 ; c2: P1, P2, P3 ; c3: P2 ; c4: P3（未来买入，as-of 应排除）
        self.as_of = date(2026, 3, 31)
        self.holdings = pd.DataFrame(
            [
                ("C1", "P001", "2025-01-01"),
                ("C1", "P002", "2025-02-01"),
                ("C2", "P001", "2025-01-01"),
                ("C2", "P002", "2025-01-01"),
                ("C2", "P003", "2025-03-01"),
                ("C3", "P002", "2025-01-01"),
                ("C4", "P003", "2026-06-01"),  # 未来，不参与
            ],
            columns=["customer_id", "product_id", "buy_date"],
        )

    def test_similarity_is_directional_p_of_j_given_i(self):
        sim = build_co_holding_similarity(self.holdings, as_of=self.as_of)
        lookup = {
            (row.product_id_i, row.product_id_j): row.similarity
            for row in sim.itertuples(index=False)
        }
        # P001 持有者 C1/C2，两人都持有 P002 -> 1.0
        self.assertAlmostEqual(lookup[("P001", "P002")], 1.0)
        # P002 持有者 C1/C2/C3，其中两人持有 P001 -> 2/3
        self.assertAlmostEqual(lookup[("P002", "P001")], 2 / 3)
        # P001 -> P003：C2 一人持有 P3 -> 1/2
        self.assertAlmostEqual(lookup[("P001", "P003")], 0.5)

    def test_as_of_excludes_future_purchases(self):
        # C4 在 as-of 之后的 P003 买入不参与统计：
        # 计入未来买入时 P003 持有者变多，sim(P003->P001) 会从 1.0 降为 0.5
        sim = build_co_holding_similarity(self.holdings, as_of=self.as_of)
        lookup = {
            (row.product_id_i, row.product_id_j): row.similarity
            for row in sim.itertuples(index=False)
        }
        self.assertAlmostEqual(lookup[("P003", "P001")], 1.0)
        self.assertAlmostEqual(lookup[("P003", "P002")], 1.0)

    def test_customer_cf_scores_max_and_self_exclusion(self):
        sim = build_co_holding_similarity(self.holdings, as_of=self.as_of)
        scores = customer_cf_scores(
            sim,
            {"C3": ("P002",), "C9": ()},
            ["P001", "P002", "P003"],
        )
        # C3 持有 P002：sim(P002->P001)=2/3, sim(P002->P003)=1/3
        self.assertAlmostEqual(scores[("C3", "P001")], 2 / 3)
        self.assertAlmostEqual(scores[("C3", "P003")], 1 / 3)
        # 已持有的 P002 不参与信号（精确持有走另一条信号）
        self.assertNotIn(("C3", "P002"), scores)
        # 无持仓客户无信号
        self.assertNotIn(("C9", "P001"), scores)


if __name__ == "__main__":
    unittest.main()
