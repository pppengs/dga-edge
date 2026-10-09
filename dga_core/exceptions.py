# -*- coding: utf-8 -*-
"""dga_core.exceptions

Exception hierarchy for the DGA diagnosis core.

Design rule: the core never silently fabricates a diagnosis. Every situation
where a method cannot legitimately produce an answer is signalled explicitly,
either as a raised exception (bad input) or as a sentinel result code
(method not applicable / no decision).
"""


class DGAError(Exception):
    """Base class for all dga_core errors."""


class DGAValidationError(DGAError):
    """Input data failed schema or physical-plausibility validation."""


class MissingGasError(DGAError):
    """A gas concentration required by the requested method was not supplied."""


class InsufficientGasData(DGAError):
    """Gas values are present but too small/degenerate to form a ratio."""
