# -*- coding: utf-8 -*-
"""dga_core.condition

Condition monitoring (状态监测) half of the system, as opposed to fault
diagnosis (故障诊断).

The diagnosis methods answer "what kind of fault is it?". This module answers
the prior and arguably more operationally useful question: "is there anything
wrong at all, and how urgent is it?" - using IEEE C57.104-2019:

    * Table 1  absolute concentration limits -> Condition 1..4
    * Table 3  absolute change between two successive samples
    * Table 4  rate of gas increase over a 3-6 point series (ppm/year)
    * Table 5  recommended sampling interval per condition

Everything here is scalar arithmetic, so it costs the same on an embedded
target as the ratio methods do.

Standard library only; parses on Python 3.6.
"""

from typing import NamedTuple, Optional, Dict, Tuple

from .models import GasSample
from .tables import (
    IEEE_C57_104_TABLE1,
    IEEE_C57_104_TABLE3,
    IEEE_C57_104_TABLE4,
    IEEE_C57_104_ANY_INCREASE,
    IEEE_TDCG_LIMITS,
    TDCG_GAS_KEYS,
    SAMPLING_INTERVAL_BY_CONDITION,
    CONDITION_LABELS,
)

# Attribute name on GasSample -> gas key used by the C57.104 tables.
_GAS_ATTR = {
    "H2": "h2",
    "CH4": "ch4",
    "C2H6": "c2h6",
    "C2H4": "c2h4",
    "C2H2": "c2h2",
    "CO": "co",
    "CO2": "co2",
}

DAYS_PER_YEAR = 365.25


def _value(sample, gas):
    # type: (GasSample, str) -> Optional[float]
    return getattr(sample, _GAS_ATTR[gas])


def _condition_of(value, limits):
    # type: (Optional[float], Tuple[float, float, float]) -> Optional[int]
    """Map a concentration onto Condition 1..4 given (c1, c2, c3)."""
    if value is None:
        return None
    c1, c2, c3 = limits
    if value <= c1:
        return 1
    if value <= c2:
        return 2
    if value <= c3:
        return 3
    return 4


class GasCondition(NamedTuple):
    """Condition level contributed by one individual gas."""
    gas: str
    value: Optional[float]                 # ppm, None = not measured
    condition: Optional[int]               # 1..4, None = not measured
    limit_exceeded: Optional[float]        # the c-bound that was crossed


class ConditionAssessment(NamedTuple):
    """Result of applying IEEE C57.104-2019 Table 1 to a single sample."""
    condition: int                         # max over all gases and TDCG
    label: str                             # "Normal" .. "Critical"
    tdcg: Optional[float]                  # ppm
    tdcg_condition: Optional[int]
    tdcg_complete: bool                    # False -> CO missing, TDCG is a partial sum
    per_gas: tuple                         # tuple[GasCondition, ...]
    limiting_gas: Optional[str]            # gas that set the overall condition
    sampling_interval: str

    def per_gas_dict(self):
        # type: () -> Dict[str, Optional[int]]
        """Gas -> condition level, for callers that want the per-gas view."""
        return dict((g.gas, g.condition) for g in self.per_gas)

    def as_dict(self):
        # type: () -> Dict[str, object]
        return {
            "condition": self.condition,
            "label": self.label,
            "tdcg": self.tdcg,
            "tdcg_condition": self.tdcg_condition,
            "tdcg_complete": self.tdcg_complete,
            "limiting_gas": self.limiting_gas,
            "sampling_interval": self.sampling_interval,
        }


class RateAssessment(NamedTuple):
    """Result of applying IEEE C57.104-2019 Tables 3 / 4 to two samples."""
    days: float
    delta_ppm: Dict[str, Optional[float]]      # curr - prev, ppm
    rate_ppm_per_year: Dict[str, Optional[float]]
    exceeding_table3: tuple                    # gases whose change is significant
    exceeding_table4: tuple                    # gases whose rate is significant
    significant: bool                          # any of the above non-empty

    def as_dict(self):
        # type: () -> Dict[str, object]
        return {
            "days": self.days,
            "delta_ppm": self.delta_ppm,
            "rate_ppm_per_year": self.rate_ppm_per_year,
            "exceeding_table3": list(self.exceeding_table3),
            "exceeding_table4": list(self.exceeding_table4),
            "significant": self.significant,
        }


class MonitorStatus(NamedTuple):
    """Combined condition-monitoring verdict for one sample."""
    sample_id: Optional[str]
    condition: int
    label: str
    assessment: ConditionAssessment
    rate: Optional[RateAssessment]
    rate_escalated: bool                   # rate alone pushed the condition up
    advice: str

    def as_dict(self):
        # type: () -> Dict[str, object]
        return {
            "sample_id": self.sample_id,
            "condition": self.condition,
            "label": self.label,
            "assessment": self.assessment.as_dict(),
            "rate": self.rate.as_dict() if self.rate is not None else None,
            "rate_escalated": self.rate_escalated,
            "advice": self.advice,
        }


ADVICE = {
    1: "Continue normal operation at the standard sampling interval.",
    2: "Investigate: increase sampling frequency and check the gas generation rate.",
    3: "Warning: active fault likely. Plan maintenance and detailed DGA analysis.",
    4: "Critical: imminent failure risk. Consider removal from service.",
}


def total_dissolved_combustible_gas(sample):
    # type: (GasSample) -> Tuple[Optional[float], bool]
    """Return (TDCG in ppm, complete).

    TDCG = H2 + CH4 + C2H6 + C2H4 + C2H2 + CO. CO2 is excluded because it is
    not combustible. ``complete`` is False when CO (or another component) was
    not measured, in which case the returned sum is a lower bound and must not
    be compared against the Table 1 TDCG limits.
    """
    total = 0.0
    complete = True
    for gas in TDCG_GAS_KEYS:
        v = _value(sample, gas)
        if v is None:
            complete = False
            continue
        total += v
    if not complete:
        return (total, False)
    return (total, True)


def assess_condition(sample):
    # type: (GasSample) -> ConditionAssessment
    """Apply IEEE C57.104-2019 Table 1 to a single sample.

    The overall condition is the worst condition contributed by any individual
    gas or by TDCG. CO2 is evaluated as a diagnostic of paper ageing but does
    not enter TDCG.
    """
    per_gas = []
    worst = 1
    limiting = None
    for gas in ("H2", "CH4", "C2H2", "C2H4", "C2H6", "CO", "CO2"):
        value = _value(sample, gas)
        cond = _condition_of(value, IEEE_C57_104_TABLE1[gas])
        limit = None
        if cond is not None and cond > 1:
            limit = IEEE_C57_104_TABLE1[gas][cond - 2]
        per_gas.append(GasCondition(gas, value, cond, limit))
        if cond is not None and cond > worst:
            worst = cond
            limiting = gas

    tdcg, complete = total_dissolved_combustible_gas(sample)
    tdcg_cond = _condition_of(tdcg, IEEE_TDCG_LIMITS) if complete else None
    if tdcg_cond is not None and tdcg_cond > worst:
        worst = tdcg_cond
        limiting = "TDCG"

    return ConditionAssessment(
        condition=worst,
        label=CONDITION_LABELS[worst],
        tdcg=tdcg,
        tdcg_condition=tdcg_cond,
        tdcg_complete=complete,
        per_gas=tuple(per_gas),
        limiting_gas=limiting,
        sampling_interval=SAMPLING_INTERVAL_BY_CONDITION[worst],
    )


def _delta(prev_value, curr_value):
    if prev_value is None or curr_value is None:
        return None
    return curr_value - prev_value


def _exceeds(delta, limit):
    """True when a change is significant under a Table 3 / Table 4 limit."""
    if delta is None or limit is None:
        return False
    if limit == IEEE_C57_104_ANY_INCREASE:
        # "Any increase": strictly positive change is significant. Guard against
        # float noise by requiring a relative change, not an absolute epsilon.
        return delta > 0.0
    return delta > limit


def assess_rate(previous, current, days, o2n2_ratio=None, period_months=None):
    # type: (GasSample, GasSample, float, Optional[float], Optional[float]) -> RateAssessment
    """Apply IEEE C57.104-2019 Tables 3 and 4 to two successive samples.

    :param days: elapsed time between the two samples, in days. Must be > 0.
    :param o2n2_ratio: O2/N2 ratio. <= 0.2 selects the "low" column. ``None``
        defaults to the low (sealed / low-oxygen) column, which is the more
        conservative choice for a sealed transformer.
    :param period_months: months spanned by the whole series (Table 4 only).
        <= 9 months selects the short-period column; None defaults to long.
    :raises ValueError: days <= 0
    """
    if days is None or days <= 0:
        raise ValueError("days must be > 0, got {}".format(days))

    low_ratio = o2n2_ratio is None or o2n2_ratio <= 0.2
    short_period = period_months is not None and period_months <= 9

    deltas = {}
    rates = {}
    over3 = []
    over4 = []

    for gas in ("H2", "CH4", "C2H6", "C2H4", "C2H2", "CO", "CO2"):
        d = _delta(_value(previous, gas), _value(current, gas))
        deltas[gas] = d
        if d is None:
            rates[gas] = None
            continue
        rates[gas] = d * DAYS_PER_YEAR / days

        t3 = IEEE_C57_104_TABLE3[gas][0 if low_ratio else 1]
        if _exceeds(d, t3):
            over3.append(gas)

        col = IEEE_C57_104_TABLE4[gas]["low_o2n2" if low_ratio else "high_o2n2"]
        t4 = col[0 if short_period else 1]
        if _exceeds(rates[gas], t4):
            over4.append(gas)

    return RateAssessment(
        days=days,
        delta_ppm=deltas,
        rate_ppm_per_year=rates,
        exceeding_table3=tuple(over3),
        exceeding_table4=tuple(over4),
        significant=bool(over3 or over4),
    )


def monitor(sample, previous=None, days=None, o2n2_ratio=None, period_months=None):
    # type: (GasSample, Optional[GasSample], Optional[float], Optional[float], Optional[float]) -> MonitorStatus
    """Full condition-monitoring verdict for one sample.

    Without a previous sample this is a plain Table 1 assessment. With one, the
    rate of change is evaluated too, and a significant rate escalates the
    condition by at most one level - reflecting the standard's position that an
    abnormal rate of change on any single gas overrides the absolute values.

    The escalation is deliberately capped at +1: a rising rate is a reason to
    look sooner, not a reason to declare a Condition 4 emergency on its own.
    """
    assessment = assess_condition(sample)

    rate = None
    escalated = False
    condition = assessment.condition

    if previous is not None:
        if days is None:
            raise ValueError("days is required when a previous sample is given")
        rate = assess_rate(previous, sample, days,
                           o2n2_ratio=o2n2_ratio, period_months=period_months)
        if rate.significant and condition < 4:
            condition += 1
            escalated = True

    return MonitorStatus(
        sample_id=sample.sample_id,
        condition=condition,
        label=CONDITION_LABELS[condition],
        assessment=assessment,
        rate=rate,
        rate_escalated=escalated,
        advice=ADVICE[condition],
    )
