from __future__ import annotations

from dataclasses import dataclass
from math import erf, exp, log, sqrt


TRADING_DAYS_PER_YEAR = 252.0


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


@dataclass(frozen=True)
class ProbabilityInputs:
    spot: float
    threshold: float
    trading_days: float
    session_vol: float
    overnight_vol: float
    drift: float = 0.0
    session_weight: float = 0.75

    def validate(self) -> None:
        if self.spot <= 0 or self.threshold <= 0:
            raise ValueError("spot and threshold must be positive")
        if self.trading_days <= 0:
            raise ValueError("trading_days must be positive")
        if self.session_vol < 0 or self.overnight_vol < 0:
            raise ValueError("volatility cannot be negative")
        if not 0 <= self.session_weight <= 1:
            raise ValueError("session_weight must be between 0 and 1")


def effective_annualized_vol(inputs: ProbabilityInputs) -> float:
    """Blend session and overnight annualized variance using a calibrated weight."""
    inputs.validate()
    overnight_weight = 1.0 - inputs.session_weight
    variance = (
        inputs.session_weight * inputs.session_vol**2
        + overnight_weight * inputs.overnight_vol**2
    )
    return sqrt(variance)


def probability_above(inputs: ProbabilityInputs) -> float:
    """Estimate P(S_T > threshold) under a lognormal real-world process."""
    sigma = effective_annualized_vol(inputs)
    years = inputs.trading_days / TRADING_DAYS_PER_YEAR
    if sigma == 0:
        terminal = inputs.spot * exp(inputs.drift * years)
        return 1.0 if terminal > inputs.threshold else 0.0

    z = (
        log(inputs.spot / inputs.threshold)
        + (inputs.drift - 0.5 * sigma**2) * years
    ) / (sigma * sqrt(years))
    return max(0.0, min(1.0, _normal_cdf(z)))
