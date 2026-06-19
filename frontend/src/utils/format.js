/**
 * Centralized amount formatting utilities.
 *
 * All components should import from here instead of defining their own
 * formatAmount / formatCompactAmount inline.
 */

/**
 * Format a number as a full euro amount: €1,234,567.89
 *
 * @param {number|null|undefined} amount - The amount to format
 * @param {object} [options]
 * @param {string} [options.emptyText=''] - Text to return when amount is 0 / null / undefined
 * @param {string} [options.locale] - Locale override (default: user's locale)
 * @returns {string} Formatted amount string
 */
export const formatAmount = (amount, { emptyText = '', locale } = {}) => {
  if (!amount || amount === 0) return emptyText;
  return `€${amount.toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

/**
 * Format a number in compact notation: €1.2M / €500K / €1,234
 *
 * @param {number|null|undefined} amount
 * @returns {string} Formatted compact amount string
 */
export const formatCompactAmount = (amount) => {
  if (amount >= 1_000_000) {
    return `€${(amount / 1_000_000).toFixed(1)}M`;
  }
  if (amount >= 1_000) {
    return `€${(amount / 1_000).toFixed(0)}K`;
  }
  return `€${amount?.toLocaleString() || 0}`;
};
