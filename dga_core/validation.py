# -*- coding: utf-8 -*-
"""dga_core.validation

Input validation for DGA samples. Zero third-party dependencies.

Two distinct classes of problem are handled:
  * Structural  - wrong type, missing required gas  -> raise
  * Plausibility- negative value, absurd magnitude  -> raise, but configurable
"""

import math

from .exceptions import DGAValidationError, MissingGasError
from .models import GasSample

# Upper plausibility bound for a dissolved gas concentration in ppm.
# IEC 60599 typical-value tables top out well below this; 1e6 is a guard rail
# against unit-confusion (e.g. uL/L vs %) rather than a physical limit.
MAX_PLAUSIBLE_PPM = 1.0e6

# Real DGA datasets routinely encode "below detection limit" as a tiny sentinel
# (e.g. 1e-4 ppm). It is NOT an error, but it does make the ratio degenerate,
# which is why it is reported separately instead of being silently zeroed.
DEFAULT_SENTINEL_ZERO = 1.0e-3


def _check_value(name, value, allow_negative=False, strict=True):
    # type: (str, float, bool, bool) -> None
    if value is None:
        return
    if isinstance(value, bool):
        raise DGAValidationError("{}: boolean is not a valid concentration".format(name))
    if not isinstance(value, (int, float)):
        raise DGAValidationError("{}: expected number, got {}".format(name, type(value).__name__))
    if math.isnan(value) or math.isinf(value):
        raise DGAValidationError("{}: NaN/Inf is not a valid concentration".format(name))
    if not allow_negative and value < 0:
        raise DGAValidationError("{}: negative concentration ({})".format(name, value))
    if strict and value > MAX_PLAUSIBLE_PPM:
        raise DGAValidationError(
            "{}: implausible concentration ({} ppm) - check units".format(name, value))


def validate(sample, required_gases=None, strict=True):
    """Validate a GasSample in place.

    :param required_gases: iterable of gas attribute names that must be present.
                           Defaults to the five key DGA gases.
    :raises DGAValidationError: value fails type / plausibility checks
    :raises MissingGasError: a required gas is None
    """
    if not isinstance(sample, GasSample):
        raise DGAValidationError("expected GasSample, got {}".format(type(sample).__name__))

    for name in ("h2", "ch4", "c2h6", "c2h4", "c2h2", "co", "co2"):
        _check_value(name, getattr(sample, name), strict=strict)

    if required_gases is None:
        required_gases = ("h2", "ch4", "c2h6", "c2h4", "c2h2")

    missing = [g for g in required_gases if getattr(sample, g) is None]
    if missing:
        raise MissingGasError("missing required gas(es): {}".format(", ".join(missing)))

    return sample


def flag_sentinel_zeros(sample, threshold=DEFAULT_SENTINEL_ZERO):
    """Return the gas names whose value looks like a 'below detection limit'
    sentinel rather than a real measurement.

    This matters because such values silently produce misleadingly extreme
    ratios (e.g. C2H2 = 1e-4 makes C2H2/C2H4 -> ~0).
    """
    flagged = []
    for name in ("h2", "ch4", "c2h6", "c2h4", "c2h2", "co", "co2"):
        v = getattr(sample, name)
        if v is not None and 0 < v < threshold:
            flagged.append(name)
    return flagged
