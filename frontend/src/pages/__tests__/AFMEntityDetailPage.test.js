import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { TranslationProvider } from '../../contexts/TranslationContext';
import { ThemeProvider } from '../../contexts/ThemeContext';
import { AuthProvider } from '../../contexts/AuthContext';
import { AuthConfigProvider } from '../../contexts/AuthConfigContext';
import { ViewportProvider } from '../../contexts/ViewportContext';
import AFMEntityDetailPage from '../AFMEntityDetailPage';

// Captured per-render so tests can assert what the page asked for.
let lastDecisionsParams = null;

jest.mock('../../api/client', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
}));
const apiClient = require('../../api/client').default;

jest.mock('../../hooks/useDecisionsList', () => ({
  __esModule: true,
  default: ({ params }) => {
    lastDecisionsParams = params;
    return {
      decisions: [],
      pagination: { total_items: 0 },
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

jest.mock('react-markdown', () => ({ children }) => <div>{children}</div>);
jest.mock('remark-gfm', () => () => {});

class MockIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
global.IntersectionObserver = MockIntersectionObserver;

// Entity activity spans Jan 2024 – Sep 2026 (33 months).
const DATE_RANGE_PAYLOAD = {
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

const ENTITY_PAYLOAD = {
  entity: {
    afm: '802388731',
    name: 'Γ ΓΑΒΡΙΗΛΙΔΗΣ ΣΙΑ Ε Ε',
    total_appearances: 42,
    first_seen: '2024-01-15',
    last_seen: '2026-09-28',
  },
};

beforeEach(() => {
  lastDecisionsParams = null;
  apiClient.get.mockReset();
  apiClient.get.mockImplementation((url) => {
    if (url.includes('/system/config/auth/')) {
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
    if (url.includes('/companies/afm/')) return Promise.resolve({ data: null });
    // Entity metadata endpoint — must come after the /companies/ check.
    if (/\/entity\/afm\/[^/]+\/$/.test(url)) return Promise.resolve({ data: ENTITY_PAYLOAD });
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
                  <Route path="/entity/afm/:afm" element={<AFMEntityDetailPage />} />
                </Routes>
              </ViewportProvider>
            </AuthProvider>
          </ThemeProvider>
        </TranslationProvider>
      </AuthConfigProvider>
    </MemoryRouter>
  );

describe('AFMEntityDetailPage date-window seeding', () => {
  test('seeds the window from ?start_date/&end_date instead of the progressive default', async () => {
    // This is the page /entity/afm/:afm actually renders (more specific route
    // than /entity/:entityType/:entityId), i.e. where dashboard cards land.
    renderPage('/entity/afm/802388731?start_date=2025-09-29&end_date=2026-09-28');

    await waitFor(() => expect(lastDecisionsParams).not.toBeNull());

    expect(lastDecisionsParams.start_date).toBe('2025-09-29');
    expect(lastDecisionsParams.end_date).toBe('2026-09-28');
  });

  test('falls back to the progressive default when the URL has no window', async () => {
    renderPage('/entity/afm/802388731');

    await waitFor(() => expect(lastDecisionsParams).not.toBeNull());

    // Progressive default → only Sep 2026 qualifies (≥5 decisions).
    expect(lastDecisionsParams.start_date).toBe('2026-09-01');
    expect(lastDecisionsParams.end_date).toBe('2026-09-30');
  });

  test('clamps a seeded window that reaches past the entity data span', async () => {
    renderPage('/entity/afm/802388731?start_date=2023-01-01&end_date=2026-09-28');

    await waitFor(() => expect(lastDecisionsParams).not.toBeNull());

    expect(lastDecisionsParams.start_date).toBe('2024-01-01');
    expect(lastDecisionsParams.end_date).toBe('2026-09-30');
  });
});
