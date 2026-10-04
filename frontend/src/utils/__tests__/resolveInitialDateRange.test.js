import { createDynamicDateRangeUtils, resolveInitialDateRange } from '../dateUtils';

// Entity activity spans Jan 2024 – Sep 2026 → 33 months (indices 0..32).
const dateRangePayload = {
  has_data: true,
  date_range: { earliest: '2024-01-15', latest: '2026-09-28', span_days: 988 },
  activity_chart: {
    stats: { max_amount: 7 },
    data: [
      { month: '2025-09', count: 0, amount: 0 },
      { month: '2026-08', count: 0, amount: 0 },
      { month: '2026-09', count: 7, amount: 7 },
    ],
  },
};

const dateUtils = createDynamicDateRangeUtils(dateRangePayload);

describe('resolveInitialDateRange', () => {
  test('uses the URL window verbatim when it is inside the data span', () => {
    const { monthRange, timeRange } = resolveInitialDateRange(
      dateUtils,
      '2025-09-29',
      '2026-09-28'
    );

    // Sep 2025 is index 20; Sep 2026 is index 32.
    expect(monthRange).toEqual({ startIndex: 20, endIndex: 32 });
    // Not clamped → the exact dates the linking card used.
    expect(timeRange).toEqual({
      startDate: '2025-09-29',
      endDate: '2026-09-28',
    });
  });

  test('clamps and snaps the window when it reaches before the data span', () => {
    const { monthRange, timeRange } = resolveInitialDateRange(
      dateUtils,
      '2023-01-01',
      '2026-09-28'
    );

    expect(monthRange).toEqual({ startIndex: 0, endIndex: 32 });
    // Snapped to the clamped month edges, not the raw URL dates.
    expect(timeRange).toEqual({
      startDate: '2024-01-01',
      endDate: '2026-09-30',
    });
  });

  test('clamps an end date that reaches past the data span', () => {
    const { monthRange, timeRange } = resolveInitialDateRange(
      dateUtils,
      '2026-09-01',
      '2030-01-01'
    );

    expect(monthRange).toEqual({ startIndex: 32, endIndex: 32 });
    expect(timeRange).toEqual({
      startDate: '2026-09-01',
      endDate: '2026-09-30',
    });
  });

  test('falls back to the progressive default when the URL has no window', () => {
    const { monthRange, timeRange } = resolveInitialDateRange(
      dateUtils,
      undefined,
      undefined,
      dateRangePayload.activity_chart.data
    );

    // Progressive default: walk back until ≥5 decisions → only Sep 2026.
    expect(monthRange).toEqual({ startIndex: 32, endIndex: 32 });
    expect(timeRange).toEqual({
      startDate: '2026-09-01',
      endDate: '2026-09-30',
    });
  });

  test('ignores malformed URL dates and falls back to the default', () => {
    const { monthRange } = resolveInitialDateRange(
      dateUtils,
      'not-a-date',
      'also-bad',
      dateRangePayload.activity_chart.data
    );
    expect(monthRange).toEqual({ startIndex: 32, endIndex: 32 });
  });

  test('normalises a reversed URL window', () => {
    const { monthRange, timeRange } = resolveInitialDateRange(
      dateUtils,
      '2026-09-28',
      '2025-09-29'
    );

    expect(monthRange).toEqual({ startIndex: 20, endIndex: 32 });
    expect(timeRange).toEqual({
      startDate: '2025-09-29',
      endDate: '2026-09-28',
    });
  });
});
