/**
 * Format a Date as YYYY-MM-DD in LOCAL time.
 *
 * NEVER use date.toISOString().split('T')[0] — toISOString() converts
 * to UTC, shifting dates across midnight for timezones ahead of UTC.
 * A midnight Date in Athens (UTC+3) becomes the previous day in UTC.
 */
export const toLocalISODate = (d) => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

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

// Re-exported from utils/format.js for backward compatibility.
// Prefer importing directly from '../utils/format' in new code.
export { formatAmount } from './format';

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
      const targetYear = startYear + Math.floor((startMonth + index) / 12);
      const targetMonth = (startMonth + index) % 12;
      if (isEndOfMonth) {
        // Last day of targetMonth: day 0 of the next month
        const lastDay = new Date(targetYear, targetMonth + 1, 0).getDate();
        return `${targetYear}-${String(targetMonth + 1).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;
      }
      return `${targetYear}-${String(targetMonth + 1).padStart(2, '0')}-01`;
    },

    // Get default range (last 3 months or full range if less)
    getDefaultRange: () => {
      const defaultSpan = Math.min(totalMonths, 3);
      return {
        startIndex: Math.max(0, totalMonths - defaultSpan),
        endIndex: totalMonths - 1
      };
    },

    // Get progressive default range: expand backwards from the most recent
    // month until we hit a cumulative threshold of decisions (or cap out).
    // Falls back to getDefaultRange() when no activity data is available.
    getProgressiveDefaultRange: (activityData) => {
      const THRESHOLD = 5;   // stop expanding once we've seen this many decisions
      const MAX_MONTHS = 12; // never expand beyond 12 months

      if (!activityData || activityData.length === 0) {
        return this.getDefaultRange();
      }

      // activityData is ordered oldest → newest; reverse so we walk backwards
      const months = activityData.slice().reverse();
      let cumulative = 0;
      let takeMonths = 1;

      for (let i = 0; i < months.length; i++) {
        cumulative += months[i].count;
        takeMonths = i + 1;
        if (cumulative >= THRESHOLD && takeMonths >= 1) break;
        if (takeMonths >= MAX_MONTHS) break;
      }

      return {
        startIndex: Math.max(0, totalMonths - takeMonths),
        endIndex: totalMonths - 1
      };
    }
  };
};

/**
 * Resolve a page's initial date window from the URL, falling back to the
 * entity's progressive default.
 *
 * Shared by `EntityDetailPage` and `AFMEntityDetailPage` — both are reachable
 * from dashboard cards that rank entities over a specific period, and both
 * must land on that same window or the page disagrees with the card that
 * linked to it.
 *
 * Seeding rules:
 *  - No (or invalid) URL dates → progressive default range.
 *  - URL dates within the entity's data span → used verbatim, so the window
 *    matches the linking card exactly.
 *  - URL dates outside the span → clamped to the available months, and the
 *    QUERY window is snapped to the clamped month edges so the request can't
 *    contradict what the slider shows.
 *
 * @param {object} dateUtils            result of createDynamicDateRangeUtils()
 * @param {string|undefined} urlStartDate  YYYY-MM-DD from ?start_date
 * @param {string|undefined} urlEndDate    YYYY-MM-DD from ?end_date
 * @param {Array|undefined} activityData   entityDateRange.activity_chart.data
 * @returns {{monthRange: {startIndex: number, endIndex: number},
 *            timeRange: {startDate: string, endDate: string}}}
 */
export const resolveInitialDateRange = (
  dateUtils,
  urlStartDate,
  urlEndDate,
  activityData
) => {
  if (urlStartDate && urlEndDate) {
    const start = new Date(urlStartDate);
    const end = new Date(urlEndDate);

    if (!isNaN(start.getTime()) && !isNaN(end.getTime())) {
      const maxIdx = dateUtils.totalMonths - 1;
      const rawStartIdx = dateUtils.dateToIndex(start);
      const rawEndIdx = dateUtils.dateToIndex(end);

      // Clamp to the months this entity actually has data for, so the slider
      // handles can never overflow the track.
      const startIdx = Math.max(0, Math.min(maxIdx, rawStartIdx));
      const endIdx = Math.max(0, Math.min(maxIdx, rawEndIdx));

      const lo = Math.min(startIdx, endIdx);
      const hi = Math.max(startIdx, endIdx);
      const wasClamped = startIdx !== rawStartIdx || endIdx !== rawEndIdx;

      // A reversed link (?start_date after ?end_date) is malformed; normalise
      // it so the range is always ascending.
      const [fromDate, toDate] =
        rawStartIdx <= rawEndIdx
          ? [urlStartDate, urlEndDate]
          : [urlEndDate, urlStartDate];

      return {
        monthRange: { startIndex: lo, endIndex: hi },
        timeRange: wasClamped
          ? {
              startDate: dateUtils.indexToDateString(lo),
              endDate: dateUtils.indexToDateString(hi, true),
            }
          : { startDate: fromDate, endDate: toDate },
      };
    }
  }

  const defaultRange = dateUtils.getProgressiveDefaultRange(activityData);
  return {
    monthRange: defaultRange,
    timeRange: {
      startDate: dateUtils.indexToDateString(defaultRange.startIndex),
      endDate: dateUtils.indexToDateString(defaultRange.endIndex, true),
    },
  };
};
