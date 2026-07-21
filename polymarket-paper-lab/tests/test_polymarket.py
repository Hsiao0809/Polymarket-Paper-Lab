import unittest
from unittest.mock import patch

from paperlab.polymarket import fetch_finance_markets


class PublicMarketTests(unittest.TestCase):
    @patch("paperlab.polymarket._get_json")
    def test_parses_and_filters_nested_markets(self, get_json):
        get_json.return_value = {
            "events": [
                {
                    "title": "SPY Daily Up or Down",
                    "slug": "spy-up-or-down-test",
                    "endDate": "2026-07-20T20:00:00Z",
                    "markets": [
                        {
                            "question": "Will SPY close up?",
                            "slug": "will-spy-close-up",
                            "liquidityNum": 2500,
                            "volumeNum": 12000,
                            "bestBid": 0.48,
                            "bestAsk": 0.51,
                            "fees_enabled": True,
                        },
                        {
                            "question": "Unrelated threshold",
                            "slug": "unrelated-threshold",
                        },
                    ],
                }
            ]
        }

        markets = fetch_finance_markets(limit=20, title_filter="close up")

        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].event_slug, "spy-up-or-down-test")
        self.assertEqual(markets[0].best_ask, 0.51)
        self.assertTrue(markets[0].fees_enabled)
        requested_url = get_json.call_args.args[0]
        self.assertIn("tag_slug=finance", requested_url)
        self.assertIn("order=volume_24hr", requested_url)


if __name__ == "__main__":
    unittest.main()
