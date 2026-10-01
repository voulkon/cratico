"""
Data-quality detector registry.

Import this package — not the individual detector modules — everywhere a
detector needs to be discovered.  Adding a detector is: write the subclass,
call ``register()`` at the bottom of this module, add a test case.  No caller
changes.

    from core.services.data_quality import resolve_detectors, run_detectors

    for detector in resolve_detectors(job.mode):
        ...

Detectors are stateless singletons (all configuration is class-level), so
``get_detector()`` returns the shared instance.
"""

from __future__ import annotations

from core.services.data_quality.base import (
    TARGET_AMOUNT,
    TARGET_UNUSABLE,
    STATUS_APPLIED,
    STATUS_CONSISTENT,
    STATUS_DETECTED,
    STATUS_ERROR,
    STATUS_SKIPPED,
    BaseDetector,
    DetectorRun,
    Finding,
    Outcome,
    run_detectors,
    summarize,
)
from core.services.data_quality.decimal_shift import DecimalShiftDetector
from core.services.data_quality.non_monetary import NonMonetaryValueDetector

__all__ = [
    # detectors
    "DecimalShiftDetector",
    "NonMonetaryValueDetector",
    # base types
    "BaseDetector",
    "DetectorRun",
    "Finding",
    "Outcome",
    "STATUS_APPLIED",
    "STATUS_CONSISTENT",
    "STATUS_DETECTED",
    "STATUS_ERROR",
    "STATUS_SKIPPED",
    "TARGET_AMOUNT",
    "TARGET_UNUSABLE",
    # registry
    "REGISTRY",
    "MODES",
    "MODE_BOTH",
    "register",
    "get_detector",
    "all_detectors",
    "detector_slugs",
    "resolve_detectors",
    "resolve_mode_bounds",
    "describe_detectors",
    "run_detectors",
    "summarize",
]

#: ``AmountCorrectionJob.mode`` value that runs every registered detector.
MODE_BOTH = "both"

#: slug → detector instance, in display / execution order.
REGISTRY: dict[str, BaseDetector] = {}

#: The mode values ``resolve_detectors`` understands.  A mode runs every
#: detector whose ``mode_key`` matches, plus everything for ``both``.
MODES: dict[str, str] = {
    "decimal_shift": "Decimal separator shift only",
    "non_monetary": "Non-monetary value (AFM/KAE) only",
    MODE_BOTH: "Every registered detector",
}


def register(detector: BaseDetector) -> BaseDetector:
    """Register a detector singleton.  Raises on a duplicate slug."""
    if not detector.slug:
        raise ValueError(f"{type(detector).__name__} has no slug")
    if detector.slug in REGISTRY:
        raise ValueError(f"duplicate detector slug: {detector.slug!r}")
    if detector.mode_key not in MODES or detector.mode_key == MODE_BOTH:
        raise ValueError(
            f"{detector.slug}: mode_key {detector.mode_key!r} is not a valid "
            f"mode (add it to MODES)"
        )
    REGISTRY[detector.slug] = detector
    return detector


def get_detector(slug: str) -> BaseDetector:
    """Return the registered detector for *slug* (KeyError if unknown)."""
    try:
        return REGISTRY[slug]
    except KeyError:
        raise KeyError(
            f"unknown detector {slug!r} — registered: {', '.join(REGISTRY) or '(none)'}"
        ) from None


def all_detectors() -> list[BaseDetector]:
    """Every registered detector, in registration order."""
    return list(REGISTRY.values())


def detector_slugs() -> list[str]:
    return list(REGISTRY)


def resolve_detectors(mode: str) -> list[BaseDetector]:
    """
    Expand a job ``mode`` into the detectors to run.

    ``both`` (or ``"all"``) → every detector; otherwise the detectors whose
    ``mode_key`` equals *mode*.  An unknown mode raises, so a typo can never
    silently correct nothing.
    """
    if mode in (MODE_BOTH, "all", None, ""):
        return all_detectors()
    if mode not in MODES:
        raise ValueError(
            f"unknown detector mode {mode!r} — valid: {', '.join(MODES)}"
        )
    return [d for d in REGISTRY.values() if d.mode_key == mode]


def resolve_mode_bounds(mode: str) -> tuple:
    """
    Narrowest amount window that covers every detector in *mode*.

    Returns ``(min_amount, max_amount)``, each ``None`` when unbounded.  Used
    by the admin form / job to show what a mode will scan when the operator
    leaves the amount fields empty.
    """
    detectors = resolve_detectors(mode)
    mins = [d.default_min_amount for d in detectors if d.default_min_amount is not None]
    maxes = [d.default_max_amount for d in detectors if d.default_max_amount is not None]
    # Any detector without a max means unbounded; otherwise take the widest.
    max_amount = max(maxes) if maxes and len(maxes) == len(detectors) else None
    return (min(mins) if mins else None, max_amount)


def describe_detectors() -> list[dict]:
    """Metadata for the admin / API (mirrors ``get_available_processes``)."""
    return [
        {
            "slug": d.slug,
            "name": d.name,
            "description": d.description,
            "mode": d.mode_key,
            "needs_text": d.needs_text,
            "can_repair": d.can_repair,
            "uses_total_amount": d.uses_total_amount,
            "min_amount": str(d.default_min_amount) if d.default_min_amount else None,
            "max_amount": str(d.default_max_amount) if d.default_max_amount else None,
        }
        for d in all_detectors()
    ]


# ── Registration ───────────────────────────────────────────────────────────
# Order matters only for display and for which finding "wins" in a summary.
register(DecimalShiftDetector())
register(NonMonetaryValueDetector())
