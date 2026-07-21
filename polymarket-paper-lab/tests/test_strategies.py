import unittest

from paperlab.strategies import (
    BuyLeg,
    evaluate_complete_set,
    evaluate_containment,
    evaluate_partition,
    scan_strategy_payload,
)


class StructuralStrategyTests(unittest.TestCase):
    def test_complete_set_detects_fee_adjusted_candidate(self):
        result = evaluate_complete_set(
            "complete",
            BuyLeg("YES", ask=0.44, ask_size=100, slippage=0.001),
            BuyLeg("NO", ask=0.45, ask_size=80, slippage=0.001),
            verified_complements=True,
            min_profit_per_set=0.005,
        )
        self.assertEqual(result.action, "PAPER_CANDIDATE")
        self.assertGreater(result.locked_profit_per_set, 0)
        self.assertEqual(result.capacity_sets, 80)

    def test_complete_set_rejects_false_midpoint_edge_after_costs(self):
        result = evaluate_complete_set(
            "not cheap",
            BuyLeg("YES", ask=0.49, ask_size=100),
            BuyLeg("NO", ask=0.50, ask_size=100),
            verified_complements=True,
            min_profit_per_set=0.005,
        )
        self.assertEqual(result.action, "NO_TRADE")
        self.assertLess(result.locked_profit_per_set, 0.005)

    def test_containment_requires_verified_logic(self):
        result = evaluate_containment(
            "unverified",
            BuyLeg("NO subset", ask=0.40, ask_size=20),
            BuyLeg("YES superset", ask=0.40, ask_size=20),
            verified_containment=False,
            min_profit_per_set=0.005,
        )
        self.assertEqual(result.action, "NO_TRADE")
        self.assertTrue(any("not verified" in reason for reason in result.reasons))

    def test_partition_requires_exhaustive_outcomes(self):
        result = evaluate_partition(
            "incomplete",
            (BuyLeg("A", 0.30, 10), BuyLeg("B", 0.30, 10)),
            mutually_exclusive=True,
            exhaustive=False,
            min_profit_per_set=0.005,
        )
        self.assertEqual(result.action, "NO_TRADE")

    def test_payload_scans_all_strategy_types(self):
        payload = {
            "complete_sets": [
                {
                    "name": "one",
                    "verified_complements": True,
                    "yes": {"label": "Y", "ask": 0.44, "ask_size": 10},
                    "no": {"label": "N", "ask": 0.44, "ask_size": 10},
                }
            ],
            "containment_pairs": [],
            "partitions": [],
        }
        report = scan_strategy_payload(payload)
        self.assertEqual(len(report.candidates), 1)
        self.assertEqual(len(report.opportunities), 1)


if __name__ == "__main__":
    unittest.main()
