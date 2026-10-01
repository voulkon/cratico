"""
Data-quality detector framework — base types and contract.

A *detector* answers one question about one decision: **"is a recorded value
wrong, and wrong in this specific, recognisable way?"**  It is the single place
where a data-quality algorithm is defined.  The registry
(``core.services.data_quality``) makes detectors discoverable, and the generic
runners (batch job, post-import sweep, admin, management commands) consume the
registry instead of hard-coding algorithm names.

Detector vs. text process
-------------------------
``core.services.text_processes`` answers *"does this text contain X?"* — pure,
text-only, reusable (dates, AFMs, amounts).  A **detector** answers *"does this
decision's recorded data disagree with the source?"* — it owns a verdict, a
candidate query, and (optionally) a treatment.  A detector may *use* text
processes (``DecimalShiftDetector`` uses the cents-based amount detector);
a text process never flags a decision.

Rules every detector MUST follow
--------------------------------
1. **Detect and treat are separate.**  ``scan()`` is read-only; ``apply()``
   writes.  ``apply()`` returning 0 rows unconditionally makes the detector a
   pure *reporter* (it surfaces the problem but cannot fix it).
2. **Never invent a monetary value.**  If the real amount is unknown, flag the
   row (``invalid_amount_reason``) — never write a guess into
   ``verified_amount``.  See ``docs/lessons_learnt/non_monetary_value_as_amount.md``.
3. **Own your candidate query.**  ``candidate_ids()`` is the ONLY definition of
   "which decisions this detector can act on".  Every caller (batch job,
   post-import sweep, CLI, admin) goes through it.  Never duplicate the
   predicate next to a call site.
4. **Declare your inputs.**  ``needs_text = True`` means the detector reads the
   document (download + extract, expensive); ``False`` means DB-only.
5. **Declare your amount bounds.**  Misrecorded values are numerically
   ambiguous, so bounds (defaults in ``default_min_amount`` /
   ``default_max_amount``) are what keep a historical sweep tractable.
6. **Be idempotent.**  Re-running ``apply()`` on an already-treated decision must
   be a no-op, or rewrite the identical value.
7. **Delegate writes.**  ``apply()`` must call the owning service
   (``AmountCorrectionService``) rather than re-implementing the persistence —
   one write path, one set of invariants.

Adding a detector is then: subclass → implement ``candidate_ids`` / ``scan`` /
``apply`` → ``register()`` in the package ``__init__`` → add a data-driven test
case.  No caller changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Sequence

from loguru import logger

#: A finding that the value is *missing* rather than *different*.
TARGET_AMOUNT = "amount"
#: A finding that the recorded amount must not be used as money at all.
TARGET_UNUSABLE = "unusable"

#: Outcome statuses shared by every detector.
STATUS_DETECTED = "detected"       # findings exist, nothing written
STATUS_APPLIED = "applied"         # findings exist and were written
STATUS_CONSISTENT = "consistent"   # nothing wrong
STATUS_SKIPPED = "skipped"         # could not be judged (no text, no fields)
STATUS_ERROR = "error"             # the detector raised


@dataclass(frozen=True)
class Finding:
    """
    One discrepancy: the recorded value of one target disagrees with the source.

    ``recorded`` / ``suggested`` are strings so any detector can report any
    shape of value.  ``suggested`` is empty when the real value is unknown
    (which is exactly the "flag, don't guess" case).
    """

    #: Detector-local kind, e.g. ``"afm"`` / ``"decimal_shift"``.
    kind: str
    #: Stable machine reason, e.g. ``"afm_as_amount"`` — stored on the model.
    reason: str
    #: What kind of target is wrong (``TARGET_AMOUNT`` / ``TARGET_UNUSABLE``).
    target: str = TARGET_AMOUNT
    #: ``DecisionAmountField.id`` when the finding is field-scoped.
    field_id: int | None = None
    #: Metadata field the value came from, e.g. ``"sponsor[6].expenseAmount"``.
    source_field: str = ""
    #: What the database currently holds.
    recorded: str = ""
    #: The corrected value, or ``""`` when it is unknown.
    suggested: str = ""
    #: Human-readable note; carries the detector's ``[MARKER]`` tag.
    note: str = ""
    #: Extra structured detail (matched value, clone factor, ...).
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Flatten for storage in ``AmountCorrectionJobResult`` JSON columns."""
        return {
            "kind": self.kind,
            "reason": self.reason,
            "target": self.target,
            "field_id": self.field_id,
            "source_field": self.source_field,
            "recorded": self.recorded,
            "suggested": self.suggested,
            "note": self.note,
            "payload": self.payload,
        }


@dataclass
class Outcome:
    """The result of running one detector over one decision."""

    slug: str
    status: str
    findings: list[Finding] = field(default_factory=list)
    #: Rows written by ``apply()`` (always 0 for a dry run / a reporter).
    written: int = 0
    #: Why the detector abstained (``STATUS_SKIPPED`` only).
    reason: str = ""
    #: Free-form detector detail, surfaced in job results and logs.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def detected(self) -> bool:
        return bool(self.findings)

    @property
    def repaired(self) -> bool:
        """True when the detector wrote an actual correction."""
        return self.written > 0 and any(f.suggested for f in self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "detector": self.slug,
            "status": self.status,
            "written": self.written,
            "reason": self.reason,
            "findings": [f.as_dict() for f in self.findings],
            "meta": self.meta,
        }


class BaseDetector:
    """
    Base class for data-quality detectors.

    Attributes are class-level because detectors are stateless singletons
    registered in ``core.services.data_quality``.
    """

    #: Stable identifier — persisted in job `mode` values and CLI output.
    slug: str = ""
    #: Value of ``AmountCorrectionJob.mode`` (or ``"both"``) that runs this
    #: detector.  Defaults to the slug with dashes → underscores.
    mode_key: str = ""
    name: str = ""
    description: str = ""
    #: ``[MARKER]`` tag prepended to notes, so a note can be grepped.
    note_marker: str = ""

    #: True when the detector needs the document text (expensive: download +
    #: extract).  False = DB-only, safe to run over the whole backlog.
    needs_text: bool = False
    #: True when the detector can replace the recorded value with a derived
    #: one.  False = it can only flag the row as unusable.
    can_repair: bool = False

    #: Amount bounds used when the caller does not supply its own.
    default_min_amount: Decimal | None = None
    default_max_amount: Decimal | None = None
    #: True when the detector keys on the *aggregate* decision total rather
    #: than on individual amount fields.
    uses_total_amount: bool = False

    def __init__(self) -> None:
        if not self.mode_key:
            self.mode_key = self.slug.replace("-", "_")

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    def candidate_ids(
        self,
        *,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        imported_since=None,
        imported_until=None,
        issue_start=None,
        issue_end=None,
        limit: int | None = None,
    ) -> list[int]:
        """
        Return the ids of decisions this detector could act on.

        The caller-facing bounds are ``min_amount`` / ``max_amount`` (mapped to
        the existing job fields).  ``imported_since`` is inclusive,
        ``imported_until`` exclusive — both filter on ``Decision.created_at``
        (import time), never on ``issue_date``.  ``issue_start`` / ``issue_end``
        filter on ``issue_date_day`` instead (inclusive).
        """
        raise NotImplementedError

    def scan(self, decision, **kwargs) -> Outcome:
        """Read-only detection.  Must not write anything."""
        raise NotImplementedError

    def apply(self, decision, outcome: Outcome, **kwargs) -> int:
        """
        Write the treatment for ``outcome``'s findings; return rows written.

        MUST delegate to the owning service.  Honours ``dry_run``.
        """
        return 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def bounds(
        self,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Fill missing bounds from the detector's declared defaults."""
        if min_amount is None:
            min_amount = self.default_min_amount
        if max_amount is None:
            max_amount = self.default_max_amount
        return min_amount, max_amount

    def finding(
        self,
        *,
        kind: str,
        reason: str,
        note: str = "",
        **kwargs: Any,
    ) -> Finding:
        """Build a finding, stamping the detector's marker onto the note."""
        if note and self.note_marker and not note.startswith(self.note_marker):
            note = f"{self.note_marker} {note}"
        return Finding(kind=kind, reason=reason, note=note, **kwargs)

    def skip(self, reason: str) -> Outcome:
        return Outcome(slug=self.slug, status=STATUS_SKIPPED, reason=reason)


@dataclass
class DetectorRun:
    """One detector's outcome for one decision, plus the write if any."""

    detector: BaseDetector
    outcome: Outcome

    @property
    def slug(self) -> str:
        return self.detector.slug


def run_detectors(
    decision,
    detectors: Sequence[BaseDetector],
    *,
    dry_run: bool = False,
    apply: bool = True,
    **kwargs: Any,
) -> list[DetectorRun]:
    """
    Scan *decision* with every detector and (unless dry-running) treat it.

    A detector that raises never aborts the others: it is logged and reported
    as ``STATUS_ERROR``.  ``kwargs`` (``read_if_missing``, ``use_raw_context``,
    ...) are forwarded verbatim to ``scan`` / ``apply`` so detectors stay
    free to declare what they need.
    """
    runs: list[DetectorRun] = []
    for detector in detectors:
        try:
            outcome = detector.scan(decision, **kwargs)
        except Exception as exc:
            logger.exception(
                f"Detector {detector.slug} failed to scan decision "
                f"{getattr(decision, 'id', '?')}: {exc}"
            )
            runs.append(
                DetectorRun(
                    detector,
                    Outcome(
                        slug=detector.slug,
                        status=STATUS_ERROR,
                        reason=str(exc)[:255],
                    ),
                )
            )
            continue

        if apply and not dry_run and outcome.detected:
            try:
                outcome.written = detector.apply(
                    decision, outcome, dry_run=dry_run, **kwargs
                )
                if outcome.written:
                    outcome.status = STATUS_APPLIED
            except Exception as exc:
                logger.exception(
                    f"Detector {detector.slug} failed to treat decision "
                    f"{getattr(decision, 'id', '?')}: {exc}"
                )
                outcome.status = STATUS_ERROR
                outcome.reason = str(exc)[:255]

        runs.append(DetectorRun(detector, outcome))

    return runs


def _entry(run: DetectorRun, finding: Finding) -> dict[str, Any]:
    """Flatten a finding into the dict shape job results / the admin render."""
    entry: dict[str, Any] = {"detector": run.slug}
    entry.update(finding.as_dict())
    return entry


def summarize(runs: Iterable[DetectorRun]) -> dict[str, Any]:
    """
    Fold detector runs into one job-result-shaped summary.

    ``status`` picks the most significant outcome so the batch job counters
    stay meaningful: a repair beats a flag, a flag beats "clean", an error
    beats everything.  A repair is only counted as such when the detector
    actually wrote it — a dry run reports the same findings with
    ``status="would_correct"`` so the admin can preview without mutating.
    """
    runs = list(runs)
    corrections: list[dict[str, Any]] = []
    flagged: list[dict[str, Any]] = []
    reasons: list[str] = []
    written = 0

    for run in runs:
        written += run.outcome.written
        if run.outcome.reason:
            reasons.append(run.outcome.reason)
        for finding in run.outcome.findings:
            entry = _entry(run, finding)
            if finding.suggested:
                corrections.append(entry)
            else:
                flagged.append(entry)

    dry_run = bool(corrections) and written == 0

    if any(r.outcome.status == STATUS_ERROR for r in runs):
        status = STATUS_ERROR
    elif corrections:
        status = "would_correct" if dry_run else "corrected"
    elif flagged:
        # A single shared reason is the honest status; mixed kinds are generic.
        unique = {f["reason"] for f in flagged}
        status = unique.pop() if len(unique) == 1 else "non_monetary_value_as_amount"
    elif runs and all(r.outcome.status == STATUS_CONSISTENT for r in runs):
        status = "consistent"
    elif any(r.outcome.status == STATUS_SKIPPED for r in runs):
        status = "no_text_amounts_found" if "no_text" in reasons else "skipped"
    else:
        status = "consistent"

    return {
        "status": status,
        "detectors": [r.slug for r in runs],
        "corrections": corrections,
        "flagged": flagged,
        "written": written,
        "group_correction": any(
            f.get("payload", {}).get("group_correction") for f in corrections
        ),
        "reason": "; ".join(dict.fromkeys(reasons))[:255],
    }
