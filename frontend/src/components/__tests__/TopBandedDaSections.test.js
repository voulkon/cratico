import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { TranslationProvider } from '../../contexts/TranslationContext';
import TopBandedDaReceiversSection from '../TopBandedDaReceiversSection';
import TopBandedDaGiversSection from '../TopBandedDaGiversSection';

jest.mock('../../api/client', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));
const apiClient = require('../../api/client').default;

// Fixed date range so the section fetches immediately. Must be a STABLE
// object reference — the section's data-loading effect depends on
// `dateRange`, so a fresh object per render would loop forever.
// Name is `mock*` so jest's hoisted mock factory can reference it.
const mockDateRange = { start_date: '2026-01-01', end_date: '2026-01-31' };
jest.mock('../../contexts/DateRangeContext', () => ({
  __esModule: true,
  useDateRange: () => ({ dateRange: mockDateRange }),
}));

// jsdom has no IntersectionObserver.
class MockIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
global.IntersectionObserver = MockIntersectionObserver;

// Renders the location it landed on so tests can assert the navigation target.
const LocationProbe = () => {
  const location = useLocation();
  return (
    <div
      data-testid="location-probe"
      data-pathname={location.pathname}
      data-search={location.search}
    />
  );
};

const renderWithProviders = (ui) =>
  render(
    <MemoryRouter>
      <TranslationProvider>{ui}</TranslationProvider>
    </MemoryRouter>
  );

const receiversResponse = {
  data: {
    metric: 'Most €30k–€38k Direct Assignments Received',
    results: [
      {
        rank: 1,
        entity_afm: '111111111',
        entity_name: 'ACME LTD',
        decision_count: 3,
        banded_amount_sum: '99000.00',
      },
    ],
    pagination: { total_count: 1, has_more: false },
  },
};

const giversResponse = {
  data: {
    metric: 'Most €30k–€38k Direct Assignments Issued',
    results: [
      {
        rank: 1,
        organization_uid: '900000001',
        organization_label: 'ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ',
        decision_count: 5,
        banded_amount_sum: '165000.00',
      },
    ],
    pagination: { total_count: 1, has_more: false },
  },
};

afterEach(() => {
  jest.clearAllMocks();
});

describe('TopBandedDaReceiversSection', () => {
  it('renders ranked recipients from the banded DA endpoint', async () => {
    apiClient.get.mockResolvedValue(receiversResponse);

    renderWithProviders(<TopBandedDaReceiversSection collapsible />);

    await waitFor(() => expect(screen.getByText('ACME LTD')).toBeInTheDocument());

    expect(apiClient.get).toHaveBeenCalledWith(
      expect.stringContaining('/decisions/top-banded-da-receivers/')
    );
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.getByText('€99K')).toBeInTheDocument();
  });

  it('links to the entity page carrying the date window and direct_assignments_only', async () => {
    apiClient.get.mockResolvedValue(receiversResponse);

    renderWithProviders(
      <Routes>
        <Route
          path="/"
          element={<TopBandedDaReceiversSection collapsible directOnly />}
        />
        <Route path="/entity/afm/:afm" element={<LocationProbe />} />
      </Routes>
    );

    await waitFor(() => expect(screen.getByText('ACME LTD')).toBeInTheDocument());
    await userEvent.click(screen.getByText('ACME LTD'));

    const probe = screen.getByTestId('location-probe');
    expect(probe).toHaveAttribute('data-pathname', '/entity/afm/111111111');
    const params = new URLSearchParams(probe.getAttribute('data-search'));
    expect(params.get('start_date')).toBe('2026-01-01');
    expect(params.get('end_date')).toBe('2026-01-31');
    expect(params.get('direct_assignments_only')).toBe('true');
  });
});

describe('TopBandedDaGiversSection', () => {
  it('renders ranked issuers from the banded DA endpoint', async () => {
    apiClient.get.mockResolvedValue(giversResponse);

    renderWithProviders(<TopBandedDaGiversSection collapsible />);

    await waitFor(() =>
      expect(screen.getByText('ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ')).toBeInTheDocument()
    );

    expect(apiClient.get).toHaveBeenCalledWith(
      expect.stringContaining('/decisions/top-banded-da-givers/')
    );
    expect(screen.getByText('#1')).toBeInTheDocument();
  });

  it('links to the organization page carrying the date window and direct_assignments_only', async () => {
    apiClient.get.mockResolvedValue(giversResponse);

    renderWithProviders(
      <Routes>
        <Route
          path="/"
          element={<TopBandedDaGiversSection collapsible directOnly />}
        />
        <Route path="/entity/organization/:uid" element={<LocationProbe />} />
      </Routes>
    );

    await waitFor(() =>
      expect(screen.getByText('ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ')).toBeInTheDocument()
    );
    await userEvent.click(screen.getByText('ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ'));

    const probe = screen.getByTestId('location-probe');
    expect(probe).toHaveAttribute('data-pathname', '/entity/organization/900000001');
    const params = new URLSearchParams(probe.getAttribute('data-search'));
    expect(params.get('start_date')).toBe('2026-01-01');
    expect(params.get('end_date')).toBe('2026-01-31');
    expect(params.get('direct_assignments_only')).toBe('true');
  });
});
