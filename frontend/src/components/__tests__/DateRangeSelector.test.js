/**
 * T14: the period selector exposes the intraday 'today' preset.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { TranslationProvider } from '../../contexts/TranslationContext';
import { DateRangeProvider } from '../../contexts/DateRangeContext';
import DateRangeSelector from '../DateRangeSelector';

beforeAll(() => {
  localStorage.setItem('preferred-language', 'en');
});

const renderSelector = () =>
  render(
    <MemoryRouter>
      <TranslationProvider>
        <DateRangeProvider>
          <DateRangeSelector />
        </DateRangeProvider>
      </TranslationProvider>
    </MemoryRouter>
  );

describe('DateRangeSelector', () => {
  it("renders a 'Today' period button", () => {
    renderSelector();
    expect(screen.getByRole('button', { name: 'Today' })).toBeInTheDocument();
  });

  it('still renders the existing period buttons', () => {
    renderSelector();
    ['Yesterday', 'Week', 'Month', 'Year', 'Custom'].forEach((label) => {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    });
  });
});
