from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from .decision import taker_fee_per_share


Action = Literal["PAPER_CANDIDATE", "NO_TRADE"]


@dataclass(frozen=True)
class BuyLeg:
    label: str
    ask: float
    ask_size: float
    fee_rate: float = 0.04
    slippage: float = 0.005

    def validate(self) -> None:
        if not self.label.strip():
            raise ValueError("leg label cannot be empty")
        if not 0 < self.ask < 1:
            raise ValueError(f"{self.label}: ask must be between 0 and 1")
        if self.ask_size < 0:
            raise ValueError(f"{self.label}: ask_size cannot be negative")
        if self.fee_rate < 0 or self.slippage < 0:
            raise ValueError(f"{self.label}: fee_rate and slippage cannot be negative")

    @property
    def fee_per_share(self) -> float:
        return taker_fee_per_share(self.ask, self.fee_rate)

    @property
    def all_in_cost(self) -> float:
        return self.ask + self.fee_per_share + self.slippage


@dataclass(frozen=True)
class StrategyResult:
    name: str
    strategy: str
    action: Action
    legs: tuple[BuyLeg, ...]
    all_in_cost_per_set: float
    minimum_payout_per_set: float
    locked_profit_per_set: float
    locked_roi: float
    capacity_sets: float
    capacity_locked_profit: float
    reasons: tuple[str, ...]
    assumptions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        result["assumptions"] = list(self.assumptions)
        return result


@dataclass(frozen=True)
class ScanReport:
    candidates: tuple[StrategyResult, ...]

    @property
    def opportunities(self) -> tuple[StrategyResult, ...]:
        return tuple(item for item in self.candidates if item.action == "PAPER_CANDIDATE")

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "checked": len(self.candidates),
                "paper_candidates": len(self.opportunities),
                "decision": "PAPER_CANDIDATE" if self.opportunities else "NO_TRADE",
            },
            "candidates": [item.to_dict() for item in self.candidates],
            "notice": "simulation only; all legs must fill and resolution assumptions must hold",
        }


def _leg(data: dict[str, Any]) -> BuyLeg:
    try:
        leg = BuyLeg(
            label=str(data["label"]),
            ask=float(data["ask"]),
            ask_size=float(data["ask_size"]),
            fee_rate=float(data.get("fee_rate", 0.04)),
            slippage=float(data.get("slippage", 0.005)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid leg: {data!r}") from exc
    leg.validate()
    return leg


def _evaluate_bundle(
    *,
    name: str,
    strategy: str,
    legs: tuple[BuyLeg, ...],
    logic_verified: bool,
    min_profit_per_set: float,
    assumptions: tuple[str, ...],
) -> StrategyResult:
    if not legs:
        raise ValueError(f"{name}: at least one leg is required")
    for leg in legs:
        leg.validate()

    cost = sum(leg.all_in_cost for leg in legs)
    minimum_payout = 1.0
    locked_profit = minimum_payout - cost
    locked_roi = locked_profit / cost if cost > 0 else 0.0
    capacity = min(leg.ask_size for leg in legs)
    reasons: list[str] = []
    if not logic_verified:
        reasons.append("logical relationship or resolution equivalence is not verified")
    if locked_profit < min_profit_per_set:
        reasons.append(
            f"locked profit {locked_profit:.4f} < minimum {min_profit_per_set:.4f} per set"
        )
    if capacity <= 0:
        reasons.append("one or more legs have no executable ask depth")

    action: Action = "NO_TRADE" if reasons else "PAPER_CANDIDATE"
    return StrategyResult(
        name=name,
        strategy=strategy,
        action=action,
        legs=legs,
        all_in_cost_per_set=cost,
        minimum_payout_per_set=minimum_payout,
        locked_profit_per_set=locked_profit,
        locked_roi=locked_roi,
        capacity_sets=capacity,
        capacity_locked_profit=max(0.0, locked_profit) * capacity,
        reasons=tuple(reasons),
        assumptions=assumptions,
    )


def evaluate_complete_set(
    name: str,
    yes: BuyLeg,
    no: BuyLeg,
    *,
    verified_complements: bool,
    min_profit_per_set: float,
) -> StrategyResult:
    return _evaluate_bundle(
        name=name,
        strategy="complete_set",
        legs=(yes, no),
        logic_verified=verified_complements,
        min_profit_per_set=min_profit_per_set,
        assumptions=(
            "YES and NO are complementary tokens of the exact same market",
            "both legs fill at the recorded ask depth",
            "one complete set redeems for exactly 1 unit at resolution",
        ),
    )


def evaluate_containment(
    name: str,
    subset_no: BuyLeg,
    superset_yes: BuyLeg,
    *,
    verified_containment: bool,
    min_profit_per_set: float,
) -> StrategyResult:
    return _evaluate_bundle(
        name=name,
        strategy="logical_containment",
        legs=(subset_no, superset_yes),
        logic_verified=verified_containment,
        min_profit_per_set=min_profit_per_set,
        assumptions=(
            "the subset event logically implies the superset event",
            "both markets use aligned timestamps, price sources, and resolution rules",
            "buying NO(subset) plus YES(superset) has a minimum terminal payout of 1",
        ),
    )


def evaluate_partition(
    name: str,
    outcomes_yes: tuple[BuyLeg, ...],
    *,
    mutually_exclusive: bool,
    exhaustive: bool,
    min_profit_per_set: float,
) -> StrategyResult:
    return _evaluate_bundle(
        name=name,
        strategy="exhaustive_partition",
        legs=outcomes_yes,
        logic_verified=mutually_exclusive and exhaustive,
        min_profit_per_set=min_profit_per_set,
        assumptions=(
            "exactly one named outcome wins",
            "the outcome list is exhaustive and contains no unresolved placeholder",
            "all legs fill at the recorded ask depth",
        ),
    )


def scan_strategy_payload(payload: dict[str, Any], min_profit_per_set: float = 0.005) -> ScanReport:
    if min_profit_per_set < 0:
        raise ValueError("min_profit_per_set cannot be negative")
    results: list[StrategyResult] = []

    for item in payload.get("complete_sets", []):
        results.append(
            evaluate_complete_set(
                str(item["name"]),
                _leg(item["yes"]),
                _leg(item["no"]),
                verified_complements=bool(item.get("verified_complements", False)),
                min_profit_per_set=min_profit_per_set,
            )
        )

    for item in payload.get("containment_pairs", []):
        results.append(
            evaluate_containment(
                str(item["name"]),
                _leg(item["subset_no"]),
                _leg(item["superset_yes"]),
                verified_containment=bool(item.get("verified_containment", False)),
                min_profit_per_set=min_profit_per_set,
            )
        )

    for item in payload.get("partitions", []):
        results.append(
            evaluate_partition(
                str(item["name"]),
                tuple(_leg(leg) for leg in item.get("outcomes_yes", [])),
                mutually_exclusive=bool(item.get("mutually_exclusive", False)),
                exhaustive=bool(item.get("exhaustive", False)),
                min_profit_per_set=min_profit_per_set,
            )
        )

    return ScanReport(candidates=tuple(results))
