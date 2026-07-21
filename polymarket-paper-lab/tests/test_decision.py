import unittest

from paperlab.decision import MarketQuote, RiskRules, make_decision, taker_fee_per_share


class DecisionTests(unittest.TestCase):
    def test_fee_formula(self):
        self.assertAlmostEqual(taker_fee_per_share(0.5, 0.04), 0.01)

    def test_no_trade_when_edge_is_too_small(self):
        result = make_decision(
            0.52,
            MarketQuote(yes_bid=0.49, yes_ask=0.51, no_bid=0.48, no_ask=0.50, liquidity=5_000),
            bankroll=300,
        )
        self.assertEqual(result.action, "NO_TRADE")
        self.assertEqual(result.stake, 0)

    def test_trade_is_capped_at_one_percent_bankroll(self):
        result = make_decision(
            0.80,
            MarketQuote(yes_bid=0.44, yes_ask=0.46, no_bid=0.52, no_ask=0.54, liquidity=5_000),
            bankroll=300,
            rules=RiskRules(slippage_per_share=0.0),
        )
        self.assertEqual(result.action, "TRADE")
        self.assertEqual(result.selected.side, "YES")
        self.assertLessEqual(result.stake, 3.0)

    def test_liquidity_gate_blocks_signal(self):
        result = make_decision(
            0.80,
            MarketQuote(yes_bid=0.44, yes_ask=0.46, no_bid=0.52, no_ask=0.54, liquidity=100),
            bankroll=300,
        )
        self.assertEqual(result.action, "NO_TRADE")
        self.assertTrue(any("liquidity" in reason for reason in result.reasons))


if __name__ == "__main__":
    unittest.main()
