import React, { createContext, useContext, useState, useMemo } from 'react';

const DateRangeContext = createContext();

export const useDateRange = () => {
  const context = useContext(DateRangeContext);
  if (!context) {
    throw new Error('useDateRange must be used within DateRangeProvider');
  }
  return context;
};

// Helper function to calculate date ranges
const calculateDateRange = (period) => {
  const end = new Date();
  const start = new Date();

  switch (period) {
    case 'today':
      start.setHours(0, 0, 0, 0);
      end.setHours(23, 59, 59, 999);
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
  const [period, setPeriod] = useState(defaultPeriod);
  const [customRange, setCustomRange] = useState(null);

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
