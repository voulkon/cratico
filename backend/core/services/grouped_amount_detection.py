"""
Cents-based monetary amount detection for Greek documents.

This is a **high-precision** detector: in Greek official documents (Διαύγεια),
monetary amounts are almost always written with **two decimal places** (cents),
even when the amount is round — e.g. ``30.000,00``, ``1.000,00``, ``1.234.567,89``.

The defining signal is the ``,digit{2}`` suffix (comma + exactly 2 digits), NOT
the thousands grouping.  This makes false positives near-zero because protocol
numbers, dates, page numbers, and other non-monetary numbers **never** end
with a comma and exactly two digits.

In Greek official documents the convention is:
  - dot   (.) as the thousands separator
  - comma (,) as the decimal separator

Both Greek (``1.234.567,89``) and English (``1,234,567.89``) formats are
supported, but the comma-decimal form is the primary target.

This module is complementary to ``amount_text_detection`` (which also catches
bare integers and amounts without cents).  Use this when you want
*high-precision, low-recall* detection for cross-checking DB amounts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ── Regex ────────────────────────────────────────────────────────────────────
# Matches amounts that END with exactly 2 decimal places (cents):
#
#   Greek format:   1.234.567,89    30.000,00    30000,00
#   English format: 1,234,567.89    30,000.00
#
# The key signal is the `,\d{2}` suffix — no other numeric pattern in Greek
# administrative text ends with a comma and exactly two digits.
#
# Alternatives (tried left-to-right):
#   1. \d{1,3}(?:\.\d{3})*,\d{2}   — Greek: optional dot-thousands + comma-decimal
#   2. \d{1,3}(?:,\d{3})*\.\d{2}   — English: optional comma-thousands + dot-decimal
#   3. \d+,\d{2}                    — bare integer + comma-decimal (30000,00)
_CENTS_AMOUNT_RE = re.compile(
    r"""
    (?<![\d.,])                      # not preceded by digit/separator
    (?P<number>
        \d{1,3}(?:\.\d{3})*,\d{2}   # Greek: opt. dot-thousands, comma-decimal
        |
        \d{1,3}(?:,\d{3})*\.\d{2}   # English: opt. comma-thousands, dot-decimal
        |
        \d+,\d{2}                    # bare integer + comma-decimal (30000,00)
    )
    (?!\d)                           # not a numeric continuation
    \s*
    (?P<currency>€|ευρώ|EUR)?        # optional currency marker
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass
class GroupedAmount:
    """A single cents-bearing monetary amount found in text."""

    amount: Decimal
    raw: str  # the matched string, e.g. "1.234.567,89"
    position: int  # char offset in text
    near_keyword: bool = False


@dataclass
class GroupedMatchResult:
    """Result of matching one DB amount against cents-based text amounts."""

    db_amount: Decimal
    found_exact: bool = False
    #: The grouped amount in the text that matches (exact or clone)
    matched_text_amount: Decimal | None = None
    clone_factor: Decimal | None = None  # e.g. 100 (text = db × 100)

    @property
    def found(self) -> bool:
        return self.found_exact or self.matched_text_amount is not None


@dataclass
class GroupedVerificationResult:
    """Aggregate result of checking DB amounts against cents-bearing
    amounts found in the document text."""

    grouped_amounts: list[GroupedAmount] = field(default_factory=list)
    matches: list[GroupedMatchResult] = field(default_factory=list)

    @property
    def all_found(self) -> bool:
        return bool(self.matches) and all(m.found_exact for m in self.matches)

    @property
    def any_clone(self) -> bool:
        return any(m.clone_factor is not None for m in self.matches)

    @property
    def primary_grouped_amount(self) -> Decimal | None:
        """Best-guess primary amount from cents-bearing hits only."""
        if not self.grouped_amounts:
            return None
        keyword_hits = [g for g in self.grouped_amounts if g.near_keyword]
        pool = keyword_hits or self.grouped_amounts
        return max(g.amount for g in pool)


# Keyword context — amounts near these are more likely to be the primary amount
CONTEXT_KEYWORDS = (
    "ποσό", "ποσού", "δαπάνη", "προϋπολογισμ", "αξία",
    "συνολικ", "φπα", "ευρώ", "€",
)
CONTEXT_WINDOW = 80


def parse_grouped_amount(number: str) -> Decimal | None:
    """
    Parse a Greek or English formatted number string into a Decimal.

    Greek:  "1.234.567,89" -> Decimal("1234567.89")
            "30.000,00"    -> Decimal("30000.00")
            "30000,00"     -> Decimal("30000.00")
    English:"1,234,567.89" -> Decimal("1234567.89")
            "30,000.00"    -> Decimal("30000.00")
    """
    s = number.strip()
    if not s:
        return None
    try:
        # Determine which separator is the decimal:
        # - If comma appears AFTER the last dot, it's Greek (comma=decimal)
        # - If dot appears AFTER the last comma, it's English (dot=decimal)
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")

        if last_comma > last_dot:
            # Greek format: comma is decimal, dots are thousands
            int_part, _, dec_part = s.rpartition(",")
            normalised = int_part.replace(".", "") + "." + dec_part
        elif last_dot > last_comma:
            # English format: dot is decimal, commas are thousands
            int_part, _, dec_part = s.rpartition(".")
            normalised = int_part.replace(",", "") + "." + dec_part
        else:
            # Only one separator type: treat comma as decimal (Greek default)
            if "," in s:
                normalised = s.replace(",", ".")
            else:
                normalised = s
        return Decimal(normalised)
    except InvalidOperation:
        return None


def extract_grouped_amounts(text: str) -> list[GroupedAmount]:
    """
    Extract only amounts with 2 decimal places (cents) from *text*.

    In Greek official documents, monetary amounts virtually always include
    the cents (``,00`` even for round amounts).  This is the defining signal
    that separates money from other numbers (protocol IDs, dates, page refs).

    Deduplicates by (amount, position).
    """
    if not text:
        return []

    detected: list[GroupedAmount] = []
    seen: set[tuple[Decimal, int]] = set()

    for m in _CENTS_AMOUNT_RE.finditer(text):
        amount = parse_grouped_amount(m.group("number"))
        if amount is None:
            continue
        key = (amount, m.start())
        if key in seen:
            continue
        seen.add(key)

        context = text[max(0, m.start() - CONTEXT_WINDOW): m.start()].lower()
        near_keyword = any(kw in context for kw in CONTEXT_KEYWORDS)

        detected.append(
            GroupedAmount(
                amount=amount,
                raw=m.group("number"),
                position=m.start(),
                near_keyword=near_keyword,
            )
        )

    return detected


def grouped_decimal_shift_clones(amount: Decimal) -> dict[Decimal, Decimal]:
    """
    Return ×100/÷100 clones of *amount* as {clone: factor}.

    The classic Diavgeia typo: dropping the decimal comma when typing
    30.000,00 → 3.000.000 (×100 shift).
    """
    return {
        (amount * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ): Decimal("100"),
        (amount / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ): Decimal("0.01"),
    }


def verify_amounts_against_grouped(
    text: str,
    db_amounts: list[Decimal],
    tolerance: Decimal = Decimal("0.01"),
) -> GroupedVerificationResult:
    """
    Check each DB amount against **only** the grouped-thousands amounts
    detected in *text*.

    Because this only considers amounts with an unambiguous grouped format,
    an exact match is high-confidence evidence that the DB amount is correct.
    A clone match is high-confidence evidence of a decimal-shift typo.
    """
    grouped = extract_grouped_amounts(text)
    grouped_values = {g.amount for g in grouped}

    matches: list[GroupedMatchResult] = []
    for db_amount in db_amounts:
        if db_amount is None:
            continue
        result = GroupedMatchResult(db_amount=db_amount)

        # Exact match (within ±tolerance) against grouped-thousands amounts
        if any(abs(v - db_amount) <= tolerance for v in grouped_values):
            result.found_exact = True
            result.matched_text_amount = db_amount
        else:
            # Decimal-shift clones
            for clone, factor in grouped_decimal_shift_clones(db_amount).items():
                if any(abs(v - clone) <= tolerance for v in grouped_values):
                    result.matched_text_amount = clone
                    result.clone_factor = factor
                    break
        matches.append(result)

    return GroupedVerificationResult(grouped_amounts=grouped, matches=matches)
