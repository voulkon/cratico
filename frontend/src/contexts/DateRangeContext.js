import React, { createContext, useContext, useState, useMemo, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';

const DateRangeContext = createContext();

// Export the raw context so components can use useContext(DateRangeContext)
// directly for safe optional access (returns undefined when no provider exists).
export { DateRangeContext };

export const useDateRange = () => {
  const context = useContext(DateRangeContext);
  if (!context) {
    throw new Error('useDateRange must be used within DateRangeProvider');
  }
  return context;
};

// Helper function to calculate date ranges
const calculateDateRange = (period) => {
  // Base is YESTERDAY — no intraday imports yet, so the most recent
  // complete data is always the previous day.  All windows (week, month,
  // year) end at yesterday.  The 'today' case explicitly moves forward.
  const end = new Date();
  end.setDate(end.getDate() - 1);
  end.setHours(23, 59, 59, 999);
  const start = new Date(end);
  start.setHours(0, 0, 0, 0);

  switch (period) {
    case 'today':
      // Override: move both to today (for future intraday imports)
      start.setDate(start.getDate() + 1);
      end.setDate(end.getDate() + 1);
      break;
    case 'yesterday':
      // Already yesterday — nothing to adjust
      break;
    case 'week':
      start.setDate(end.getDate() - 7);
      break;
    case 'month':
      start.setMonth(end.getMonth() - 1);
      break;
    case 'year':
      start.setFullYear(end.getFullYear() - 1);
      break;
    case 'custom':
      // Will be set manually
      return null;
    default:
      start.setDate(end.getDate() - 7); // Default to week
  }

  return {
    start_date: start.toISOString().split('T')[0],
    end_date: end.toISOString().split('T')[0]
  };
};

export const DateRangeProvider = ({ children, defaultPeriod = 'week' }) => {
  const [searchParams, setSearchParams] = useSearchParams();

  // Read initial period from URL (?period=today) falling back to defaultPeriod
  const urlPeriod = searchParams.get('period');
  // const validPeriods = ['yesterday', 'today', 'week', 'month', 'year', 'custom'];
  const validPeriods = ['yesterday', 'week', 'month', 'year', 'custom'];
  const initialPeriod =
    urlPeriod && validPeriods.includes(urlPeriod) ? urlPeriod : defaultPeriod;

  const [period, setPeriod] = useState(initialPeriod);
  const [customRange, setCustomRange] = useState(null);

  // Keep URL in sync when period changes (so refresh preserves the selection)
  useEffect(() => {
    const current = searchParams.get('period');
    if (period === defaultPeriod) {
      // Don't pollute URL for the default period — remove the param
      if (current) {
        const next = new URLSearchParams(searchParams);
        next.delete('period');
        setSearchParams(next, { replace: true });
      }
    } else {
      if (current !== period) {
        const next = new URLSearchParams(searchParams);
        next.set('period', period);
        setSearchParams(next, { replace: true });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  // If the URL changes externally (e.g. back/forward), reflect it in state
  useEffect(() => {
    const p = searchParams.get('period');
    if (p && validPeriods.includes(p) && p !== period) {
      setPeriod(p);
    } else if (!p && period !== defaultPeriod && validPeriods.includes(period)) {
      // URL had its period removed — only reset if it's a plain default navigation
      // (we don't want to clobber a custom range mid-edit, so leave state alone here)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const dateRange = useMemo(() => {
    if (period === 'custom' && customRange) {
      return customRange;
    }
    return calculateDateRange(period);
  }, [period, customRange]);

  const value = {
    period,
    setPeriod,
    dateRange,
    setCustomRange,
    // Convenience methods
    isToday: period === 'today',
    isWeek: period === 'week',
    isMonth: period === 'month',
    isYear: period === 'year',
    isCustom: period === 'custom'
  };

  return (
    <DateRangeContext.Provider value={value}>
      {children}
    </DateRangeContext.Provider>
  );
};
