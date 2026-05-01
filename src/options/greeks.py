"""
Black-Scholes pricing and greeks for European calls.
Inputs use decimal (0.35 = 35%), outputs use per-contract conventions:
  - theta: per calendar day
  - vega: per 1 percentage point of IV

Uses math.erf to avoid a scipy dependency.
"""
from __future__ import annotations

import math


_SQRT_2 = math.sqrt(2)
_INV_SQRT_2PI = 1.0 / math.sqrt(2 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


def _norm_pdf(x: float) -> float:
    return _INV_SQRT_2PI * math.exp(-0.5 * x * x)


def bs_call(
    S: float, K: float, T: float, r: float = 0.045, sigma: float = 0.5, q: float = 0
) -> dict | None:
    """
    S: spot price
    K: strike
    T: time to expiry in years
    r: risk-free rate (default 4.5%)
    sigma: implied vol (decimal, e.g. 0.50 for 50%)
    q: continuous dividend yield
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    Nd1 = _norm_cdf(d1)
    Nd2 = _norm_cdf(d2)
    nd1 = _norm_pdf(d1)

    disc_q = math.exp(-q * T)
    disc_r = math.exp(-r * T)

    price = S * disc_q * Nd1 - K * disc_r * Nd2
    delta = disc_q * Nd1
    gamma = disc_q * nd1 / (S * sigma * sqrt_T)
    theta_annual = (
        -(S * nd1 * sigma * disc_q) / (2 * sqrt_T)
        - r * K * disc_r * Nd2
        + q * S * disc_q * Nd1
    )
    theta_daily = theta_annual / 365.0
    vega_per_pct = S * disc_q * nd1 * sqrt_T / 100.0

    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "theta": theta_daily,
        "vega": vega_per_pct,
    }


def bs_put(
    S: float, K: float, T: float, r: float = 0.045, sigma: float = 0.5, q: float = 0
) -> dict | None:
    """European put via put-call parity. Same input convention as bs_call."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    nd1 = _norm_pdf(d1)
    nm_d1 = _norm_cdf(-d1)
    nm_d2 = _norm_cdf(-d2)

    disc_q = math.exp(-q * T)
    disc_r = math.exp(-r * T)

    price = K * disc_r * nm_d2 - S * disc_q * nm_d1
    delta = -disc_q * nm_d1
    gamma = disc_q * nd1 / (S * sigma * sqrt_T)
    theta_annual = (
        -(S * nd1 * sigma * disc_q) / (2 * sqrt_T)
        + r * K * disc_r * nm_d2
        - q * S * disc_q * nm_d1
    )
    theta_daily = theta_annual / 365.0
    vega_per_pct = S * disc_q * nd1 * sqrt_T / 100.0

    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "theta": theta_daily,
        "vega": vega_per_pct,
    }
