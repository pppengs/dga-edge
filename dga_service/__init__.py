# -*- coding: utf-8 -*-
"""dga_service - batch orchestration, I/O and CLI on top of dga_core.

Standard library only. Safe for the embedded target.
"""

from .pipeline import run_batch, BatchReport
from .io_utils import read_csv, write_csv, write_jsonl

__all__ = ["run_batch", "BatchReport", "read_csv", "write_csv", "write_jsonl"]
