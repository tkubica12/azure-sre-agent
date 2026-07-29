"""PulseMart: the small FastAPI workload deployed for the Azure SRE Agent demo.

See SPEC.md section 7 ("Workload") for the behavioral contract this package
implements: a healthy checkout journey, structured telemetry, and a
deterministic, non-public failure mode used only by `labctl demo trigger`.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
