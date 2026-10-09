# -*- coding: utf-8 -*-
"""dga_core.models

Plain-data containers. Deliberately uses typing.NamedTuple rather than
dataclasses so the module imports on Python 3.6 (Jetson Nano / JetPack 4.6.4).
"""

from typing import NamedTuple, Optional, Dict

# Canonical gas keys used throughout the core.
GAS_KEYS = ("H2", "CH4", "C2H6", "C2H4", "C2H2")
GAS_KEYS_EXTENDED = ("H2", "CH4", "C2H6", "C2H4", "C2H2", "CO", "CO2")


class GasSample(NamedTuple):
    """One dissolved-gas-in-oil measurement.

    Concentrations are ppm. ``None`` means "not measured" and is distinct from
    0.0 ("measured, below detection limit is still recorded as provided").
    """
    h2: Optional[float] = None
    ch4: Optional[float] = None
    c2h6: Optional[float] = None
    c2h4: Optional[float] = None
    c2h2: Optional[float] = None
    co: Optional[float] = None
    co2: Optional[float] = None
    sample_id: Optional[str] = None

    def as_dict(self):
        # type: () -> Dict[str, Optional[float]]
        return {
            "H2": self.h2,
            "CH4": self.ch4,
            "C2H6": self.c2h6,
            "C2H4": self.c2h4,
            "C2H2": self.c2h2,
            "CO": self.co,
            "CO2": self.co2,
        }


class GasRatios(NamedTuple):
    """Derived ratios used by the classical methods.

    r1 = CH4/H2, r2 = C2H2/C2H4, r5 = C2H4/C2H6 (IEEE C57.104 numbering)
    """
    r1: Optional[float] = None   # CH4 / H2
    r2: Optional[float] = None   # C2H2 / C2H4
    r3: Optional[float] = None   # C2H2 / CH4
    r4: Optional[float] = None   # C2H6 / C2H2
    r5: Optional[float] = None   # C2H4 / C2H6


class MethodResult(NamedTuple):
    """Outcome of applying one diagnostic method to one sample."""
    method: str
    code: str                      # fault code, or NA / ND / ERR sentinel
    applicable: bool               # False -> method legitimately could not decide
    reason: Optional[str] = None   # human-readable explanation


class DiagnosisResult(NamedTuple):
    """Aggregated outcome for one sample across several methods."""
    sample_id: Optional[str]
    results: tuple                # tuple[MethodResult, ...]
    ratios: GasRatios

    def codes(self):
        # type: () -> Dict[str, str]
        return dict((r.method, r.code) for r in self.results)
