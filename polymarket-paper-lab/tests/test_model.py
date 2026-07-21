import unittest

from paperlab.model import ProbabilityInputs, effective_annualized_vol, probability_above


class ProbabilityModelTests(unittest.TestCase):
    def test_at_the_money_is_near_half(self):
        probability = probability_above(
            ProbabilityInputs(
                spot=100,
                threshold=100,
                trading_days=1,
                session_vol=0.30,
                overnight_vol=0.30,
            )
        )
        self.assertGreater(probability, 0.48)
        self.assertLess(probability, 0.50)

    def test_higher_spot_increases_probability(self):
        low = probability_above(
            ProbabilityInputs(spot=100, threshold=105, trading_days=5, session_vol=0.30, overnight_vol=0.30)
        )
        high = probability_above(
            ProbabilityInputs(spot=110, threshold=105, trading_days=5, session_vol=0.30, overnight_vol=0.30)
        )
        self.assertLess(low, high)

    def test_variance_blend(self):
        inputs = ProbabilityInputs(
            spot=100,
            threshold=100,
            trading_days=1,
            session_vol=0.20,
            overnight_vol=0.40,
            session_weight=0.75,
        )
        self.assertAlmostEqual(effective_annualized_vol(inputs), (0.75 * 0.2**2 + 0.25 * 0.4**2) ** 0.5)


if __name__ == "__main__":
    unittest.main()
