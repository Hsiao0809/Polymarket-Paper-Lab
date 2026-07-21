from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .decision import MarketQuote, RiskRules, make_decision
from .model import ProbabilityInputs, effective_annualized_vol, probability_above
from .polymarket import PublicApiError, fetch_finance_markets
from .strategies import scan_strategy_payload


def _probability(value: str) -> float:
    parsed = float(value)
    if not 0 < parsed < 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return parsed


def _positive(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paperlab",
        description="Read-only public-market discovery and paper decision research.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    score = subparsers.add_parser("score", help="score a binary stock-price market")
    score.add_argument("--question", default="Unnamed market")
    score.add_argument("--spot", type=_positive, required=True)
    score.add_argument("--threshold", type=_positive, required=True)
    score.add_argument("--days", type=_positive, required=True)
    score.add_argument("--session-vol", type=_positive, required=True)
    score.add_argument("--overnight-vol", type=_positive, required=True)
    score.add_argument("--drift", type=float, default=0.0)
    score.add_argument("--session-weight", type=float, default=0.75)
    score.add_argument("--yes-bid", type=_probability, required=True)
    score.add_argument("--yes-ask", type=_probability, required=True)
    score.add_argument("--no-bid", type=_probability, required=True)
    score.add_argument("--no-ask", type=_probability, required=True)
    score.add_argument("--liquidity", type=float, required=True)
    score.add_argument("--bankroll", type=_positive, default=300.0)
    score.add_argument("--fee-rate", type=float, default=0.04)
    score.add_argument("--slippage", type=float, default=0.005)
    score.add_argument("--min-edge", type=float, default=0.04)
    score.add_argument("--min-roi", type=float, default=0.08)
    score.add_argument("--max-spread", type=float, default=0.10)
    score.add_argument("--min-liquidity", type=float, default=1_000.0)
    score.add_argument("--json", action="store_true")

    discover = subparsers.add_parser("discover", help="list public Finance markets")
    discover.add_argument("--limit", type=int, default=20)
    discover.add_argument("--title-filter")
    discover.add_argument("--json", action="store_true")
    strategy_scan = subparsers.add_parser(
        "scan-strategies", help="scan a saved orderbook snapshot for structural paper opportunities"
    )
    strategy_scan.add_argument("--input", type=Path, required=True)
    strategy_scan.add_argument("--min-profit-per-set", type=float, default=0.005)
    strategy_scan.add_argument("--json", action="store_true")
    subparsers.add_parser("sdk-check", help="verify the official SDK installation without network or auth")
    return parser


def _run_score(args: argparse.Namespace) -> int:
    inputs = ProbabilityInputs(
        spot=args.spot,
        threshold=args.threshold,
        trading_days=args.days,
        session_vol=args.session_vol,
        overnight_vol=args.overnight_vol,
        drift=args.drift,
        session_weight=args.session_weight,
    )
    probability = probability_above(inputs)
    quote = MarketQuote(
        yes_bid=args.yes_bid,
        yes_ask=args.yes_ask,
        no_bid=args.no_bid,
        no_ask=args.no_ask,
        liquidity=args.liquidity,
    )
    rules = RiskRules(
        min_edge=args.min_edge,
        min_roi=args.min_roi,
        max_spread=args.max_spread,
        min_liquidity=args.min_liquidity,
        slippage_per_share=args.slippage,
        taker_fee_rate=args.fee_rate,
    )
    decision = make_decision(probability, quote, args.bankroll, rules)
    payload = {
        "question": args.question,
        "model_yes_probability": probability,
        "effective_annualized_vol": effective_annualized_vol(inputs),
        "decision": decision.to_dict(),
        "notice": "paper simulation only; not a live order",
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        selected = decision.selected
        print(f"Market: {args.question}")
        print(f"Model YES probability: {probability:.2%}")
        print(f"Effective annualized vol: {payload['effective_annualized_vol']:.2%}")
        print(f"Best side: {selected.side}")
        print(f"All-in cost/share: {selected.all_in_cost:.4f}")
        print(f"Net edge: {selected.edge:.2%}")
        print(f"Expected ROI: {selected.expected_roi:.2%}")
        print(f"Decision: {decision.action}")
        print(f"Paper stake: {decision.stake:.2f} USDC")
        if decision.reasons:
            print("Blocked by:")
            for reason in decision.reasons:
                print(f"- {reason}")
        print("Notice: paper simulation only; not a live order")
    return 0


def _run_discover(args: argparse.Namespace) -> int:
    try:
        markets = fetch_finance_markets(args.limit, args.title_filter)
    except (PublicApiError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([market.__dict__ for market in markets], indent=2, ensure_ascii=False))
    else:
        if not markets:
            print("No matching open Finance markets found.")
            return 0
        for market in markets:
            bid = "-" if market.best_bid is None else f"{market.best_bid:.3f}"
            ask = "-" if market.best_ask is None else f"{market.best_ask:.3f}"
            print(
                f"{market.question}\n"
                f"  end={market.end_date} bid={bid} ask={ask} "
                f"liq={market.liquidity:.0f} vol={market.volume:.0f} "
                f"fees={market.fees_enabled}\n"
                f"  https://polymarket.com/event/{market.event_slug}"
            )
    return 0


def _run_sdk_check() -> int:
    try:
        sdk_version = version("py-clob-client-v2")
        from py_clob_client_v2 import ClobClient
    except (PackageNotFoundError, ImportError) as exc:
        print("ERROR: Official SDK is not installed. Run install-sdk.cmd.", file=sys.stderr)
        print(f"DETAIL: {exc}", file=sys.stderr)
        return 2

    client = ClobClient(host="https://clob.polymarket.com", chain_id=137)
    print(f"py-clob-client-v2: {sdk_version}")
    print(f"CLOB client: {type(client).__name__} OK")
    print("authentication: not configured")
    print("mode: read-only research")
    return 0


def _run_strategy_scan(args: argparse.Namespace) -> int:
    try:
        with args.input.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        report = scan_strategy_payload(payload, args.min_profit_per_set)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        print(f"ERROR: Could not scan strategy input: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print(
        f"Checked: {len(report.candidates)} | "
        f"Paper candidates: {len(report.opportunities)} | "
        f"Decision: {'PAPER_CANDIDATE' if report.opportunities else 'NO_TRADE'}"
    )
    for result in report.candidates:
        print(f"\n[{result.action}] {result.strategy}: {result.name}")
        print(
            f"  cost/set={result.all_in_cost_per_set:.4f} "
            f"min_payout={result.minimum_payout_per_set:.4f} "
            f"locked_profit/set={result.locked_profit_per_set:.4f} "
            f"ROI={result.locked_roi:.2%}"
        )
        print(
            f"  executable_sets={result.capacity_sets:.2f} "
            f"capacity_profit={result.capacity_locked_profit:.2f}"
        )
        for leg in result.legs:
            print(
                f"  - BUY {leg.label}: ask={leg.ask:.4f} "
                f"fee={leg.fee_per_share:.4f} slippage={leg.slippage:.4f} "
                f"size={leg.ask_size:.2f}"
            )
        for reason in result.reasons:
            print(f"  blocked: {reason}")
    print("\nNotice: simulation only; all legs must fill and resolution assumptions must hold")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "score":
        return _run_score(args)
    if args.command == "discover":
        return _run_discover(args)
    if args.command == "sdk-check":
        return _run_sdk_check()
    if args.command == "scan-strategies":
        return _run_strategy_scan(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
