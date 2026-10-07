import React, { createContext, useContext, useState, useMemo, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { toLocalISODate } from '../utils/dateUtils';

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

// Periods the selector/context accepts.  'today' is enabled so first views
// of today's data hit the window the backend warms hourly (T07b/T14).
export const validPeriods = ['today', 'yesterday', 'week', 'month', 'year', 'custom'];

// Helper function to calculate date ranges
export const calculateDateRange = (period) => {
  // Base is YESTERDAY.  Week/month/year windows end at yesterday because
  // their backend cache windows are only re-warmed daily; the 'today' case
  // moves both bounds forward so it matches the window warmed hourly.
  const end = new Date();
  end.setDate(end.getDate() - 1);
  end.setHours(23, 59, 59, 999);
  const start = new Date(end);
  start.setHours(0, 0, 0, 0);

  switch (period) {
    case 'today':
      // Intraday window: move both bounds forward to today.
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
    start_date: toLocalISODate(start),
    end_date: toLocalISODate(end),
  };
};

export const DateRangeProvider = ({ children, defaultPeriod = 'week' }) => {
  const [searchParams, setSearchParams] = useSearchParams();

  // Read initial period from URL (?period=today) falling back to defaultPeriod
  const urlPeriod = searchParams.get('period');
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
