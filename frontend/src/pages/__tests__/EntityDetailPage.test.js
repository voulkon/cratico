import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { TranslationProvider } from '../../contexts/TranslationContext';
import { ThemeProvider } from '../../contexts/ThemeContext';
import { AuthProvider } from '../../contexts/AuthContext';
import { AuthConfigProvider } from '../../contexts/AuthConfigContext';
import { ViewportProvider } from '../../contexts/ViewportContext';
import EntityDetailPage from '../EntityDetailPage';

// Captured per-render so tests can assert what the page asked for.
let lastDecisionsParams = null;
let statisticsCalls = [];

jest.mock('../../api/client', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));
const apiClient = require('../../api/client').default;

jest.mock('../../hooks/useDecisionsList', () => ({
  __esModule: true,
  default: ({ params }) => {
    lastDecisionsParams = params;
    return {
      decisions: [],
      pagination: { total_count: 0 },
      loading: false,
      loadingMore: false,
      loadMore: jest.fn(),
    };
  },
}));

jest.mock('../../hooks/useDecisionTypes', () => ({
  __esModule: true,
  default: () => ({ decisionTypes: [], loading: false }),
}));

// react-markdown is pure ESM and jest 27 can't resolve it (same stub as
// App.test.js). It's only used by DecisionCard, not by this page directly.
jest.mock('react-markdown', () => ({ children }) => <div>{children}</div>);
jest.mock('remark-gfm', () => () => {});

// jsdom has no IntersectionObserver.
class MockIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
global.IntersectionObserver = MockIntersectionObserver;

// ── Fixtures ──────────────────────────────────────────────────────────────
// Entity activity spans Jan 2024 – Sep 2026 (33 months).
const DATE_RANGE_PAYLOAD = {
  has_data: true,
  entity: { name: 'Γ ΓΑΒΡΙΗΛΙΔΗΣ ΣΙΑ Ε Ε', metadata: { entity_type: 'company' } },
  date_range: { earliest: '2024-01-15', latest: '2026-09-28', span_days: 988 },
  // Last month alone holds ≥5 decisions, so the progressive default range
  // collapses to that single month — the behaviour we're overriding.
  // `stats.max_amount` and per-item `amount` are required by ActivityChart.
  activity_chart: {
    stats: { max_amount: 7 },
    data: [
      { month: '2025-09', count: 0, amount: 0 },
      { month: '2026-08', count: 0, amount: 0 },
      { month: '2026-09', count: 7, amount: 7 },
    ],
  },
};

const STATISTICS_PAYLOAD = {
  entity: { name: 'Γ ΓΑΒΡΙΗΛΙΔΗΣ ΣΙΑ Ε Ε', metadata: {} },
  summary: {
    decisions: { total_count: 1, avg_amount: 1000 },
    financial: { primary_amount: 1000, has_discrepancy: false, discrepancy_percentage: 0 },
  },
  period: { days_count: 30, start_date: '2026-09-01', end_date: '2026-09-30' },
};

beforeEach(() => {
  lastDecisionsParams = null;
  statisticsCalls = [];
  apiClient.get.mockReset();
  apiClient.get.mockImplementation((url) => {
    if (url.includes('/system/config/auth/')) {
      // Full shape — AuthConfigProvider dereferences config.authentication
      // and config.password_requirements unconditionally.
      return Promise.resolve({
        data: {
          authentication: { required: false, allowlist_enabled: false },
          password_requirements: { min_length: 8 },
          auth_methods: ['django'],
          clerk_publishable_key: null,
          search: { debounce_ms: 300 },
        },
      });
    }
    if (url.includes('view=date_range')) return Promise.resolve({ data: DATE_RANGE_PAYLOAD });
    if (url.includes('/statistics/')) {
      statisticsCalls.push(url);
      return Promise.resolve({ data: STATISTICS_PAYLOAD });
    }
    return Promise.resolve({ data: { results: [], pagination: { total_count: 0 } } });
  });
});

const renderPage = (initialEntry) =>
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AuthConfigProvider>
        <TranslationProvider>
          <ThemeProvider>
            <AuthProvider>
              <ViewportProvider>
                <Routes>
                  <Route path="/entity/:entityType/:entityId" element={<EntityDetailPage />} />
                </Routes>
              </ViewportProvider>
            </AuthProvider>
          </ThemeProvider>
        </TranslationProvider>
      </AuthConfigProvider>
    </MemoryRouter>
  );

describe('EntityDetailPage date-window seeding', () => {
  test('seeds the window from ?start_date/&end_date instead of the progressive default', async () => {
    renderPage('/entity/afm/802388731?start_date=2025-09-29&end_date=2026-09-28');

    await waitFor(() => expect(lastDecisionsParams).not.toBeNull());

    // The entity page must reuse the exact window the dashboard card used,
    // not its own (much narrower) default.
    expect(lastDecisionsParams.start_date).toBe('2025-09-29');
    expect(lastDecisionsParams.end_date).toBe('2026-09-28');

    await waitFor(() => expect(statisticsCalls.length).toBeGreaterThan(0));
    expect(statisticsCalls.some((u) => u.includes('start_date=2025-09-29'))).toBe(true);
    expect(statisticsCalls.some((u) => u.includes('end_date=2026-09-28'))).toBe(true);
  });

  test('falls back to the progressive default when the URL has no window', async () => {
    renderPage('/entity/afm/802388731');

    await waitFor(() => expect(lastDecisionsParams).not.toBeNull());

    // Progressive default: walk back from the newest month until ≥5 decisions
    // accumulate → only Sep 2026 qualifies, so the window is that month.
    expect(lastDecisionsParams.start_date).toBe('2026-09-01');
    expect(lastDecisionsParams.end_date).toBe('2026-09-30');
  });

  test('clamps a seeded window that reaches past the entity data span', async () => {
    // Start (2023-01) predates the earliest data (2024-01) → snapped forward.
    renderPage('/entity/afm/802388731?start_date=2023-01-01&end_date=2026-09-28');

    await waitFor(() => expect(lastDecisionsParams).not.toBeNull());

    expect(lastDecisionsParams.start_date).toBe('2024-01-01');
    expect(lastDecisionsParams.end_date).toBe('2026-09-30');
  });
});
