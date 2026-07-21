from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


Side = Literal["YES", "NO"]


@dataclass(frozen=True)
class RiskRules:
    min_edge: float = 0.04
    min_roi: float = 0.08
    max_spread: float = 0.10
    min_liquidity: float = 1_000.0
    max_bankroll_fraction: float = 0.01
    kelly_fraction: float = 0.25
    slippage_per_share: float = 0.005
    taker_fee_rate: float = 0.04


@dataclass(frozen=True)
class MarketQuote:
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    liquidity: float

    def validate(self) -> None:
        for name in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
            value = getattr(self, name)
            if not 0 < value < 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.yes_bid > self.yes_ask or self.no_bid > self.no_ask:
            raise ValueError("bid cannot exceed ask")
        if self.liquidity < 0:
            raise ValueError("liquidity cannot be negative")


@dataclass(frozen=True)
class SideScore:
    side: Side
    fair_probability: float
    ask: float
    fee_per_share: float
    slippage_per_share: float
    all_in_cost: float
    edge: float
    expected_roi: float
    spread: float
    kelly_fraction: float


@dataclass(frozen=True)
class Decision:
    action: Literal["TRADE", "NO_TRADE"]
    selected: SideScore
    stake: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        return result


def taker_fee_per_share(price: float, fee_rate: float) -> float:
    """Polymarket fee formula: C * rate * p * (1-p), expressed per share."""
    return fee_rate * price * (1.0 - price)


def _score_side(
    side: Side,
    fair_probability: float,
    bid: float,
    ask: float,
    rules: RiskRules,
) -> SideScore:
    fee = taker_fee_per_share(ask, rules.taker_fee_rate)
    cost = ask + fee + rules.slippage_per_share
    edge = fair_probability - cost
    roi = edge / cost if cost > 0 else 0.0
    full_kelly = max(0.0, edge / max(1e-12, 1.0 - cost))
    return SideScore(
        side=side,
        fair_probability=fair_probability,
        ask=ask,
        fee_per_share=fee,
        slippage_per_share=rules.slippage_per_share,
        all_in_cost=cost,
        edge=edge,
        expected_roi=roi,
        spread=ask - bid,
        kelly_fraction=full_kelly * rules.kelly_fraction,
    )


def make_decision(
    model_yes_probability: float,
    quote: MarketQuote,
    bankroll: float,
    rules: RiskRules | None = None,
) -> Decision:
    if not 0 <= model_yes_probability <= 1:
        raise ValueError("model_yes_probability must be between 0 and 1")
    if bankroll <= 0:
        raise ValueError("bankroll must be positive")
    quote.validate()
    rules = rules or RiskRules()

    yes = _score_side("YES", model_yes_probability, quote.yes_bid, quote.yes_ask, rules)
    no = _score_side("NO", 1.0 - model_yes_probability, quote.no_bid, quote.no_ask, rules)
    selected = max((yes, no), key=lambda item: item.edge)

    reasons: list[str] = []
    if selected.edge < rules.min_edge:
        reasons.append(f"edge {selected.edge:.3f} < minimum {rules.min_edge:.3f}")
    if selected.expected_roi < rules.min_roi:
        reasons.append(f"ROI {selected.expected_roi:.3f} < minimum {rules.min_roi:.3f}")
    if selected.spread > rules.max_spread:
        reasons.append(f"spread {selected.spread:.3f} > maximum {rules.max_spread:.3f}")
    if quote.liquidity < rules.min_liquidity:
        reasons.append(
            f"liquidity {quote.liquidity:.0f} < minimum {rules.min_liquidity:.0f}"
        )

    capped_fraction = min(selected.kelly_fraction, rules.max_bankroll_fraction)
    stake = round(bankroll * capped_fraction, 2)
    if stake <= 0:
        reasons.append("Kelly stake is zero")

    action: Literal["TRADE", "NO_TRADE"] = "NO_TRADE" if reasons else "TRADE"
    if action == "NO_TRADE":
        stake = 0.0
    return Decision(action=action, selected=selected, stake=stake, reasons=tuple(reasons))
