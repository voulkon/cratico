"""
Regex-based monetary amount detection for Greek documents.

In Greek official documents (Διαύγεια) the overwhelming convention is:
  - dot   (.) as the thousands separator
  - comma (,) as the decimal separator
e.g.  1.234.567,89 €

This module extracts every amount-like token from text, normalises it to a
``Decimal``, and then checks DB amounts (from ``DecisionAmountField``) against
the text — including the classic data-entry error where the decimal separator
is misplaced (e.g. 30.000,00 recorded as 3.000.000, i.e. a ×100 shift).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ── Regex ────────────────────────────────────────────────────────────────────
# Matches Greek-formatted numbers:
#   1.234.567,89   30.000,00   1.500   30000,00   500   0,99
# Requires either a thousands group, a decimal comma, or a bare integer.
# The number may be followed by an optional currency token.
_AMOUNT_RE = re.compile(
    r"""
    (?<![\d.,])                      # not preceded by digit/separator
    (?P<number>
        \d{1,3}(?:\.\d{3})+          # grouped thousands: 1.234.567
        (?:,\d{1,2})?                # optional decimal part
        |
        \d+                          # plain digits: 30000
        (?:,\d{1,2})?                # optional decimal part: 30000,00
    )
    (?![,.]?\d)                      # not a numeric continuation:
                                     # allow trailing . or , only when NOT
                                     # followed by a digit (e.g. sentence
                                     # period after "1.000.000.")
    \s*
    (?P<currency>€|ευρώ|EUR)?        # optional currency marker
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Keyword context (±N chars) used to rank candidate amounts — amounts appearing
# near these words are more likely to be the "primary" amount of the document.
CONTEXT_KEYWORDS = (
    "ποσό",
    "ποσού",
    "δαπάνη",
    "προϋπολογισμ",
    "αξία",
    "συνολικ",
    "φπα",
    "ευρώ",
    "€",
)
CONTEXT_WINDOW = 80  # chars before the match


@dataclass
class DetectedAmount:
    """A single amount found in text."""

    amount: Decimal
    raw: str  # the matched string, e.g. "1.234.567,89"
    position: int  # char offset in text
    near_keyword: bool = False


@dataclass
class AmountMatchResult:
    """Result of verifying one DB amount against the text."""

    db_amount: Decimal
    found_exact: bool = False
    clone_matched: Decimal | None = None  # the text value that matched a clone
    clone_factor: Decimal | None = None  # e.g. 100 (text = db × 100)

    @property
    def found(self) -> bool:
        return self.found_exact or self.clone_matched is not None


@dataclass
class TextVerificationResult:
    """Aggregate result of checking all DB amounts against document text."""

    detected_amounts: list[DetectedAmount] = field(default_factory=list)
    matches: list[AmountMatchResult] = field(default_factory=list)

    @property
    def all_found(self) -> bool:
        return bool(self.matches) and all(m.found_exact for m in self.matches)

    @property
    def any_clone(self) -> bool:
        return any(m.clone_matched is not None for m in self.matches)

    @property
    def primary_amount(self) -> Decimal | None:
        """Best-guess primary amount: prefer keyword-adjacent, then largest."""
        if not self.detected_amounts:
            return None
        keyword_hits = [d for d in self.detected_amounts if d.near_keyword]
        pool = keyword_hits or self.detected_amounts
        return max(d.amount for d in pool)


def parse_greek_amount(number: str) -> Decimal | None:
    """
    Parse a Greek-formatted number string into a Decimal.

    "1.234.567,89" -> Decimal("1234567.89")
    "30.000"       -> Decimal("30000")
    "30000,00"     -> Decimal("30000.00")
    "500"          -> Decimal("500")
    """
    s = number.strip()
    if not s:
        return None
    try:
        if "," in s:
            int_part, _, dec_part = s.rpartition(",")
            normalised = int_part.replace(".", "") + "." + dec_part
        else:
            # Only dots → thousands separators (Greek convention)
            normalised = s.replace(".", "")
        return Decimal(normalised)
    except InvalidOperation:
        return None


def extract_amounts(text: str) -> list[DetectedAmount]:
    """Extract all amounts from *text*, deduplicated by (amount, position)."""
    if not text:
        return []

    detected: list[DetectedAmount] = []
    seen: set[tuple[Decimal, int]] = set()

    for m in _AMOUNT_RE.finditer(text):
        amount = parse_greek_amount(m.group("number"))
        if amount is None:
            continue
        key = (amount, m.start())
        if key in seen:
            continue
        seen.add(key)

        context = text[max(0, m.start() - CONTEXT_WINDOW) : m.start()].lower()
        near_keyword = any(kw in context for kw in CONTEXT_KEYWORDS)

        detected.append(
            DetectedAmount(
                amount=amount,
                raw=m.group("number"),
                position=m.start(),
                near_keyword=near_keyword,
            )
        )

    return detected


def decimal_shift_clones(amount: Decimal) -> dict[Decimal, Decimal]:
    """
    Return the decimal-omitted clones of *amount* as {clone: factor}.

    The classic Diavgeia typo: the decimal comma is dropped when typing
    30.000,00  →  3.000.000  (×100 shift).  We check both directions.
    """
    return {
        (amount * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP): Decimal("100"),
        (amount / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP): Decimal(
            "0.01"
        ),
    }


def verify_amounts_in_text(
    text: str,
    db_amounts: list[Decimal],
    tolerance: Decimal = Decimal("0.01"),
) -> TextVerificationResult:
    """
    Check each DB amount against the amounts detected in *text*.

    An amount "matches exactly" if a detected value is within ±tolerance
    (default €0.01).  Otherwise its ×100 / ÷100 clones are checked; if a
    clone matches, the discrepancy is flagged with the factor.

    Returns a TextVerificationResult with per-amount match details and the
    full list of detected amounts.
    """
    detected = extract_amounts(text)
    detected_values = {d.amount for d in detected}

    matches: list[AmountMatchResult] = []
    for db_amount in db_amounts:
        if db_amount is None:
            continue
        result = AmountMatchResult(db_amount=db_amount)

        # Exact match (within ±tolerance)
        if any(abs(v - db_amount) <= tolerance for v in detected_values):
            result.found_exact = True
        else:
            # Decimal-shift clones
            for clone, factor in decimal_shift_clones(db_amount).items():
                if any(abs(v - clone) <= tolerance for v in detected_values):
                    result.clone_matched = clone
                    result.clone_factor = factor
                    break
        matches.append(result)

    return TextVerificationResult(detected_amounts=detected, matches=matches)
