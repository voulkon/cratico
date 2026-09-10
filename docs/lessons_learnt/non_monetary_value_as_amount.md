# Non-monetary value recorded as the amount

**Status:** detected, flagged, excluded from all monetary totals, and surfaced
for reporting back to Diavgeia. The real amount is still unknown per decision.
**Discovered:** 2026-09 (issue #147).

## What happens

The `expenseAmount` field holds a value that actually belongs to a **different,
non-monetary numeric field** of the same Diavgeia API response. The value
exists once, in the wrong field — it is *not* duplicated, it is **misplaced**.
It passes for an amount because it is digit-shaped and therefore looks like a
plausible 8-figure euro amount.

Two variants are currently detected:

| Variant | Value | Canonical case |
|---|---|---|
| **AFM** | counterpart VAT number (ΑΦΜ) | `Ψ0Α74690Β9-52Ρ`, `ΨΛΘΒΟΡΡ2-ΖΤΞ` |
| **KAE** | budget classification code (ΚΑΕ) | `ΨΡΙ0Ω12-0ΙΘ` |

The scope is deliberately open — other non-monetary numeric metadata (e.g. a
**protocol number**) can be covered by adding a collector plus a `KIND_*`.
Coverage today is limited to AFM and KAE.

### Why it slips through

Both values are 8-9 digit numbers, so they look like plausible euro amounts.
And since the document text literally contains the value formatted as an amount
(`99.370.337,00`), the amount pipeline's "exact match wins" policy **confirms**
the bogus value instead of flagging it.

### Canonical cases (real Diavgeia payloads)

**AFM — `Ψ0Α74690Β9-52Ρ`**

| | |
|---|---|
| Counterpart | VIOLAK INTERNATIONAL — sponsor AFM `099370337` |
| Recorded amount | `sponsor[0].expenseAmount = 99370337` (`9.9370337E7`) = €99,370,337.00 |

**AFM — `ΨΛΘΒΟΡΡ2-ΖΤΞ`**

| | |
|---|---|
| Counterpart | ΠΕΤΡΙΔΗΣ Θ ΣΠΥΡΙΔΩΝ ΚΑΙ ΣΙΑ Ε Ε — sponsor AFM `801380053` |
| Recorded amount | `sponsor[0].expenseAmount = 801380053` (`8.01380053E8`) = €801,380,053.00 |

**KAE — `Ψ0ΩΣΟΡΓΠ-Ε45`**

| | |
|---|---|
| Counterpart | GRUNDFOS ΕΛΛΑΣ ΜΟΝ ΑΕΒΕ (AFM `094393811`) |
| Recorded amount | `sponsor[0].expenseAmount = 2601000000` (`2.601E9`) = €2,601,000,000.00 |
| Sibling value | `sponsor[0].kae = "26.01.00.0000"` |

**KAE — `ΨΡΙ0Ω12-0ΙΘ`**

| | |
|---|---|
| Sponsor | ΔΕΗ (AFM `090000045`) |
| Recorded amount | `sponsor[6].expenseAmount = 706273001` (`7.06273001E8`) = €706,273,001.00 |
| Sibling value | `sponsor[6].kae = "70.6273.001"` |
| Correct siblings | `sponsor[0..5]` hold real amounts (1.571,99 / 110,44 / 2.863,00 / 11.385,97 / 60.132,07 / 27.910,03) |

Real payloads are committed as fixtures in
`core/tests/data/non_monetary_value_cases/`.

## How the guard works

`core/services/non_monetary_value_guard.py`:

- `collect_counterpart_afms(decision)` — union of `DecisionEntityRelationship`
  entities' AFMs and the raw Diavgeia sponsor metadata
  (`extra_field_values_json["sponsor"][i]["sponsorAFMName"]["afm"]`).
- `collect_kae_codes(decision)` — every `kae` value in the raw metadata
  (recursive), digit-only, ignoring values shorter than 6 digits.
- `match_non_monetary_value(amount, values, raw_span=None)` — matches a
  **whole-euro** amount (zero cents) equal to a value, leading zeros ignored,
  plus raw-text formatting variants (`99.370.337,00`, `70.6273.001,00`, …).
  A near-miss like `99.370.338,00` does **not** match.
  `match_afm_amount` / `match_kae_amount` are thin wrappers.
- `kae_code_in_raw_context(raw_context)` — the KAE stored **next to** the amount
  (`DecisionAmountField.raw_context["kae"]`): highest-precision, same-container
  signal.
- `collect_non_monetary_values(decision, use_raw_context=…)` — DB-only detector
  returning `NonMonetaryValue` rows (`kind`, `matched_value`, `reason`, `note`).
- `find_afm_amount_fields(decision)` — AFM-only convenience wrapper.

Consumers:

- `AmountVerificationService` — forces `has_discrepancy=True` and sets
  `discrepancy_reason` to `afm_as_amount` / `kae_as_amount` in
  `TextProcessRun.meta` (plus `counterpart_afm` / `counterpart_kae`), and
  prefixes the resolution note with `[AFM-AS-AMOUNT]` / `[KAE-AS-AMOUNT]`.
  Never reports confirmed. Applied in `verify_decision` and `verify_with_grouped`.
- `AmountCorrectionService` — runs the DB-only guard **before** reading the
  document, so a bogus value never costs a download/extraction. When *every*
  recorded amount is a non-monetary value it returns immediately with status
  `afm_as_amount` / `kae_as_amount` / `non_monetary_value_as_amount` and never
  touches the text. Otherwise such fields are reported in `flagged` (never in
  `corrections`) and `verified_amount` is left untouched; genuinely mis-typed
  sibling fields are still corrected normally. Batch summary counts each status.
  Detected fields are **marked invalid** (see below) unless `dry_run=True`.
- `tasks_post_import.verify_high_value_amounts` — Phase 3
  (`_discover_non_monetary_values`) sweeps everything imported that day and
  logs/counts the cases.

## The invalid-amount marker (and why it is not `verified_amount`)

There are two different kinds of "wrong amount", and conflating them would be
wrong:

| | `verified_amount` | `invalid_amount_reason` |
|---|---|---|
| Meaning | we **found** the real value in the document | we know the value is **not money**; the real value is **unknown** |
| Value written | the corrected amount | *none* — a flag + the matched AFM/KAE |

Storing `verified_amount = 0` would falsely assert a monetary value of €0 and
lose the reason. So the guard writes only a **marker** on
`DecisionAmountField`:

- `invalid_amount_reason` — `afm_as_amount` / `kae_as_amount`
- `invalid_amount_value` — the matched AFM (`099370337`) or KAE digits
- `invalid_amount_flagged_at`

Backed by the partial index `idx_daf_invalid_amounts` (mirrors
`idx_daf_verified_amounts`).</br>
`COALESCE(verified_amount, amount)` alone cannot exclude these — the marker is
NULL-safe and leaves `verified_amount` NULL, so the bogus `amount` would win the
COALESCE. Exclusion therefore happens in the **facet layer**.

### Consumers of the marker

- `core.services.decision_facets` — `_exclude_invalid_amounts()` is ANDed into
  **every** helper (`amount_sum_excluding_kae`, `effective_amount_sum`,
  `effective_amount_max`, all `effective_linked_*`) plus the
  `DecisionAmountField`-level helpers `daf_effective_sum/max/avg` and
  `daf_effective_value` (for Python loops). **Use these instead of a raw
  `Sum(Coalesce("verified_amount", "amount"))`** — several services had such
  bypasses and were showing €2.6bn payments.
- `decision_projections.paginate_decisions` — nulls `amount` and sets
  `has_invalid_amount=True` for affected decisions, so list endpoints
  (`top-by-amount`, `top-payments`, `top-direct-assignments`) never render the
  bogus figure.
- `DiavgeiaFeedbackService.pending_decisions()` + the admin feedback pool — now
  include flagged decisions, so they can be reported back to Diavgeia (the owner
  of the data). The pool shows the reason and the matched value.
- Decision detail API — exposes `has_invalid_amount`, `invalid_amount_reason`,
  `invalid_amount_value`; the detail page shows a warning instead of the amount.

## How to find affected decisions

### 0. Already-marked decisions (instant, ORM)

```python
from core.models.entities import DecisionAmountField
DecisionAmountField.objects.filter(invalid_amount_reason__isnull=False)
# or, from Decisions:
Decision.objects.filter(amount_fields__invalid_amount_reason__isnull=False).distinct()
```

### 1. Already-flagged (text-process) decisions

```python
from core.models.document_analysis import TextProcessResolution
TextProcessResolution.objects.filter(
    process="amount", note__regex=r"\[(AFM|KAE)-AS-AMOUNT\]"
)
```

`TextProcessRun.meta["discrepancy_reason"]` is `"afm_as_amount"` or
`"kae_as_amount"`.

### 2. Historical / never-verified decisions (DB-only scan)

```bash
python manage.py find_amount_anomalies --output anomalies.json
python manage.py find_amount_anomalies --kind afm --csv anomalies.csv
python manage.py find_amount_anomalies --ada ΨΛΘΒΟΡΡ2-ΖΤΞ
python manage.py find_amount_anomalies --imported-since 2026-01-01 --imported-until 2026-01-02
```

The command compares recorded `DecisionAmountField.amount` values against each
decision's AFMs/KAEs — **no document text needed** — so it also finds rows never
run through verification. It reports the ADA, the field, the matched value,
whether the guard already flagged it, and sibling amount values as hints for
the real value. `--ada` bypasses the amount bounds and uses the same-container
KAE for higher precision.

> KAE values shorter than 6 digits (e.g. the AFM case's `kae: "1311"`) are
> ignored — too likely to collide with ordinary amounts.

## Getting the real amount

The guard can tell that `99370337` / `706273001` / `801380053` is *wrong*, but
it cannot know the *right* value automatically. Practical approach:

1. Open the decision and read the document text.
2. Ignore the number that equals the AFM/KAE — look for the actual
   expense/total (often in `amountWithVAT`, `amountWithKae`, `awardAmount`, or a
   same-container sibling field). `find_amount_anomalies` prints the non-matching
   sibling candidates (e.g. `60.132,07 / 27.910,03 / 11.385,97 …` for
   `ΨΡΙ0Ω12-0ΙΘ`).
3. If the text has a clear real amount, set `verified_amount` (or re-run
   correction with the misplaced value excluded). Keep the invalid marker — or
   clear it together with the correction, whichever the review concludes.
4. If the document only contains the value, the decision is genuinely
   ambiguous — leave the invalid marker set, leave `verified_amount` empty, and
   do **not** persist the misplaced value as money. Report it via the feedback
   pool so Diavgeia can fix it at the source.

> Do **not** flag an amount merely because it *looks* like an AFM/KAE: only
> exact equality (zero cents, leading-zero-insensitive) counts.
> €99,370,338.00 is a legitimate amount even when the AFM is `099370337`.

## Tests

- `core/tests/services/test_non_monetary_value_pipeline.py` — **real API
  payloads** pushed through the full pipeline. Payload-driven and
  auto-discovering: to add a case, drop the raw API response into
  `core/tests/data/non_monetary_value_cases/` — no code changes needed. The
  expected anomalies are re-derived independently from the raw JSON by the
  test's own naive spec function (not by the guard), so it stays a genuine
  cross-check.
- `core/tests/services/test_non_monetary_value_guard.py` — synthetic
  factory-based guard unit tests, including the invalid-amount marker, its
  exclusion from `FinancialCalculationService` totals, the list projection,
  the feedback pool and the detail API.
