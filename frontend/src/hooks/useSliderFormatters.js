import { useCallback } from 'react';

export const useSliderFormatters = () => {
  const formatAmount = useCallback((amount) => {
    if (amount >= 1000000) {
      return `€${(amount / 1000000).toFixed(1)}M`;
    } else if (amount >= 1000) {
      return `€${(amount / 1000).toFixed(1)}K`;
    }
    return `€${amount.toFixed(0)}`;
  }, []);

  const formatPeriod = useCallback((period, granularity) => {
    const date = new Date(period);
    switch (granularity) {
      case 'day':
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      case 'week':
        return `Week of ${date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
      case 'month':
        return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short' });
      case 'quarter':
        return `Q${Math.floor(date.getMonth() / 3) + 1} ${date.getFullYear()}`;
      default:
        return date.toLocaleDateString();
    }
  }, []);

  return { formatAmount, formatPeriod };
};
