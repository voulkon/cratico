export const createDateRangeUtils = () => {
  const currentYear = new Date().getFullYear();
  const currentMonth = new Date().getMonth();
  const minYear = currentYear - 9;
  const maxYear = currentYear;

  const yearMonthToIndex = (year, month) => {
    return (year - minYear) * 12 + month;
  };

  const indexToYearMonth = (index) => {
    const year = minYear + Math.floor(index / 12);
    const month = index % 12;
    return { year, month };
  };

  const yearMonthToDate = (year, month, isEndDate = false) => {
    if (isEndDate) {
      const lastDay = new Date(year, month + 1, 0).getDate();
      return `${year}-${String(month + 1).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;
    }
    return `${year}-${String(month + 1).padStart(2, '0')}-01`;
  };

  const formatMonth = (year, month) => {
    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return `${monthNames[month]} ${year}`;
  };

  const defaultStartIndex = yearMonthToIndex(currentYear - 1, currentMonth);
  const defaultEndIndex = yearMonthToIndex(currentYear, currentMonth);

  return {
    currentYear,
    currentMonth,
    minYear,
    maxYear,
    yearMonthToIndex,
    indexToYearMonth,
    yearMonthToDate,
    formatMonth,
    defaultStartIndex,
    defaultEndIndex,
    maxMonthIndex: (maxYear - minYear + 1) * 12 - 1
  };
};

export const formatAmount = (amount) => {
  if (!amount || amount === 0) return 'No amount';
  return `€${amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}`;
};

export const formatDate = (dateString, options = {}) => {
  if (!dateString) return '';

  const defaultOptions = {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    ...options
  };

  return new Date(dateString).toLocaleDateString(undefined, defaultOptions);
};

export const createDynamicDateRangeUtils = (entityDateRange) => {
  if (!entityDateRange || !entityDateRange.has_data) {
    return null;
  }

  const startDate = new Date(entityDateRange.date_range.earliest);
  const endDate = new Date(entityDateRange.date_range.latest);

  // Calculate months between start and end
  const startYear = startDate.getFullYear();
  const startMonth = startDate.getMonth();
  const endYear = endDate.getFullYear();
  const endMonth = endDate.getMonth();

  const totalMonths = (endYear - startYear) * 12 + (endMonth - startMonth) + 1;

  return {
    startDate,
    endDate,
    startYear,
    startMonth,
    endYear,
    endMonth,
    totalMonths,
    spanDays: entityDateRange.date_range.span_days,

    // Convert index to actual date
    indexToDate: (index) => {
      const targetYear = startYear + Math.floor((startMonth + index) / 12);
      const targetMonth = (startMonth + index) % 12;
      return new Date(targetYear, targetMonth, 1);
    },

    // Convert date to index
    dateToIndex: (date) => {
      const year = date.getFullYear();
      const month = date.getMonth();
      return (year - startYear) * 12 + (month - startMonth);
    },

    // Format month for display
    formatMonth: (index) => {
      const date = new Date(startYear, startMonth + index, 1);
      return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short'
      });
    },

    // Convert to date string for API
    indexToDateString: (index, isEndOfMonth = false) => {
      const date = new Date(startYear, startMonth + index, isEndOfMonth ? 0 : 1);
      if (isEndOfMonth) {
        date.setMonth(date.getMonth() + 1);
        date.setDate(0);
      }
      return date.toISOString().split('T')[0];
    },

    // Get default range (last 12 months or full range if less)
    getDefaultRange: () => {
      const defaultSpan = Math.min(totalMonths, 12);
      return {
        startIndex: Math.max(0, totalMonths - defaultSpan),
        endIndex: totalMonths - 1
      };
    }
  };
};
