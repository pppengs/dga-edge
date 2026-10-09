# -*- coding: utf-8 -*-
"""dga_core - zero-dependency DGA diagnosis kernel for embedded targets.

Target: CPython 3.6+ (Jetson Nano / JetPack 4.6.4) up to 3.13.
Dependencies: standard library only.
"""

from .models import GasSample, GasRatios, MethodResult, DiagnosisResult
from .methods import (
    compute_ratios,
    iec_three_ratio,
    iec_ratio,
    rogers_ratio,
    doernenburg,
    duval_triangle1,
    diagnose,
    METHOD_REGISTRY,
    DEFAULT_METHODS,
)
from .validation import validate, flag_sentinel_zeros
from .condition import (
    GasCondition,
    ConditionAssessment,
    RateAssessment,
    MonitorStatus,
    total_dissolved_combustible_gas,
    assess_condition,
    assess_rate,
    monitor,
    ADVICE,
)
from .exceptions import (
    DGAError,
    DGAValidationError,
    MissingGasError,
    InsufficientGasData,
)

__version__ = "0.3.0"

__all__ = [
    "GasSample", "GasRatios", "MethodResult", "DiagnosisResult",
    "compute_ratios", "iec_three_ratio", "iec_ratio", "rogers_ratio", "doernenburg",
    "DEFAULT_METHODS",
    "duval_triangle1", "diagnose", "METHOD_REGISTRY",
    "validate", "flag_sentinel_zeros",
    "GasCondition", "ConditionAssessment", "RateAssessment", "MonitorStatus",
    "total_dissolved_combustible_gas", "assess_condition", "assess_rate", "monitor",
    "ADVICE",
    "DGAError", "DGAValidationError", "MissingGasError", "InsufficientGasData",
]
