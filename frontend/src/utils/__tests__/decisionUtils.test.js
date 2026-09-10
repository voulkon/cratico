/**
 * Tests for the detail-hero amount resolution in `decisionUtils`.
 *
 * Focus: a decision whose recorded amount is a non-monetary value (ΑΦΜ/ΚΑΕ)
 * must never be presented as money — but a *corrected* amount always wins,
 * with the invalid state demoted to an additional note rather than replacing
 * the hero.
 */

import {
  getHeroAmount,
  getTotalAmount,
  showInvalidAmountHero,
} from '../decisionUtils';

describe('showInvalidAmountHero', () => {
  it('is true when the decision has a flagged amount and no correction', () => {
    expect(
      showInvalidAmountHero({ has_invalid_amount: true, amount: 99370337 })
    ).toBe(true);
  });

  it('is false when a corrected amount coexists with the flag', () => {
    expect(
      showInvalidAmountHero({
        has_invalid_amount: true,
        has_corrected_amounts: true,
        corrected_amount: 3000,
        amount: 99370337,
      })
    ).toBe(false);
  });

  it('is false when the decision is clean', () => {
    expect(showInvalidAmountHero({ amount: 3000 })).toBe(false);
  });

  it('is false for a corrected decision that is not flagged', () => {
    expect(
      showInvalidAmountHero({ has_corrected_amounts: true, corrected_amount: 3000 })
    ).toBe(false);
  });

  it('tolerates a null/undefined decision', () => {
    expect(showInvalidAmountHero(null)).toBe(false);
    expect(showInvalidAmountHero(undefined)).toBe(false);
  });
});

describe('getHeroAmount', () => {
  it('prefers the corrected amount and keeps the original', () => {
    const result = getHeroAmount({
      has_corrected_amounts: true,
      corrected_amount: 3000,
      amount: 30000,
    });
    expect(result).toEqual({ value: 3000, original: 30000, isCorrected: true });
  });

  it('falls back to the raw amount when there is no correction', () => {
    expect(getHeroAmount({ amount: 30000 })).toEqual({
      value: 30000,
      original: 30000,
      isCorrected: false,
    });
  });

  it('shows the corrected amount even when the recorded amount is flagged', () => {
    const result = getHeroAmount({
      has_invalid_amount: true,
      invalid_amount_reason: 'afm_as_amount',
      amount: 99370337,
      has_corrected_amounts: true,
      corrected_amount: 3000,
    });
    expect(result.value).toBe(3000);
    expect(result.isCorrected).toBe(true);
  });

  it('ignores a null corrected_amount and keeps the raw amount unflagged', () => {
    expect(
      getHeroAmount({ has_corrected_amounts: true, corrected_amount: null, amount: 30000 })
    ).toEqual({ value: 30000, original: 30000, isCorrected: false });
  });

  it('returns null value when there is no amount at all', () => {
    expect(getHeroAmount({})).toEqual({
      value: null,
      original: null,
      isCorrected: false,
    });
  });
});

describe('getTotalAmount', () => {
  it('returns null when the recorded amount is a non-monetary value', () => {
    expect(
      getTotalAmount(
        { has_invalid_amount: true, amount: 99370337 },
        null,
        false
      )
    ).toBeNull();
  });
});
