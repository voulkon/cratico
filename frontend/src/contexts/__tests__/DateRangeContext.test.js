/**
 * Tests for the re-enabled intraday 'today' preset (T14).
 *
 * The backend warms the (today, today) analytics window hourly, so the
 * 'today' preset must resolve to exactly that window while week/month/year
 * keep ending at yesterday (their windows are only re-warmed daily).
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { toLocalISODate } from '../../utils/dateUtils';
import {
  DateRangeProvider,
  useDateRange,
  calculateDateRange,
  validPeriods,
} from '../DateRangeContext';

// Fixed local time so the local-date formatting is deterministic.
const FIXED_NOW = new Date(2026, 2, 15, 12, 0, 0); // Sun 15 Mar 2026, local

beforeEach(() => {
  jest.useFakeTimers();
  jest.setSystemTime(FIXED_NOW);
});

afterEach(() => {
  jest.useRealTimers();
});

const iso = (d) => toLocalISODate(d);

describe('validPeriods', () => {
  it("includes 'today' alongside the existing presets", () => {
    expect(validPeriods).toContain('today');
    expect(validPeriods).toEqual(
      expect.arrayContaining(['today', 'yesterday', 'week', 'month', 'year', 'custom'])
    );
  });
});

describe('calculateDateRange', () => {
  it("resolves 'today' to (today, today)", () => {
    const today = iso(FIXED_NOW);
    expect(calculateDateRange('today')).toEqual({
      start_date: today,
      end_date: today,
    });
  });

  it("keeps 'yesterday' ending yesterday", () => {
    const yesterday = iso(new Date(2026, 2, 14));
    expect(calculateDateRange('yesterday')).toEqual({
      start_date: yesterday,
      end_date: yesterday,
    });
  });

  it("keeps 'week' ending at yesterday", () => {
    expect(calculateDateRange('week')).toEqual({
      start_date: iso(new Date(2026, 2, 7)),
      end_date: iso(new Date(2026, 2, 14)),
    });
  });

  it("keeps 'month' ending at yesterday", () => {
    expect(calculateDateRange('month')).toEqual({
      start_date: iso(new Date(2026, 1, 14)),
      end_date: iso(new Date(2026, 2, 14)),
    });
  });

  it("keeps 'year' ending at yesterday", () => {
    expect(calculateDateRange('year')).toEqual({
      start_date: iso(new Date(2025, 2, 14)),
      end_date: iso(new Date(2026, 2, 14)),
    });
  });

  it("returns null for 'custom' (set manually)", () => {
    expect(calculateDateRange('custom')).toBeNull();
  });
});

describe('DateRangeProvider', () => {
  const Probe = () => {
    const { period, dateRange, isToday } = useDateRange();
    return (
      <div>
        <span data-testid="period">{period}</span>
        <span data-testid="range">
          {dateRange ? `${dateRange.start_date}|${dateRange.end_date}` : 'none'}
        </span>
        <span data-testid="is-today">{String(isToday)}</span>
      </div>
    );
  };

  const renderWithPeriod = (entry) =>
    render(
      <MemoryRouter initialEntries={[entry]}>
        <DateRangeProvider>
          <Probe />
        </DateRangeProvider>
      </MemoryRouter>
    );

  it("accepts 'today' from the URL and exposes the (today, today) range", () => {
    renderWithPeriod('/?period=today');
    const today = iso(FIXED_NOW);
    expect(screen.getByTestId('period')).toHaveTextContent('today');
    expect(screen.getByTestId('range')).toHaveTextContent(`${today}|${today}`);
    expect(screen.getByTestId('is-today')).toHaveTextContent('true');
  });
});
