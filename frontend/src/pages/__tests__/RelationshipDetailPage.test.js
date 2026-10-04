import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { TranslationProvider } from '../../contexts/TranslationContext';
import { ViewportProvider } from '../../contexts/ViewportContext';
import RelationshipDetailPage from '../RelationshipDetailPage';

// The page pulls entity/organization from the first decision, so a single
// mocked response drives the whole render.
jest.mock('../../api/client', () => ({
  __esModule: true,
  default: {
    get: jest.fn().mockResolvedValue({
      data: { has_data: false, date_range: null, activity_chart: null },
    }),
  },
}));

jest.mock('../../hooks/useDecisionsList', () => ({
  __esModule: true,
  default: ({ params }) => ({
    decisions: [
      {
        organization: { label: 'Test Org' },
        main_recipient: { afm: params.afm, name: 'Test Entity' },
      },
    ],
    pagination: {},
    loading: false,
    loadingMore: false,
    loadMore: jest.fn(),
  }),
}));

jest.mock('../../hooks/useDecisionTypes', () => ({
  __esModule: true,
  default: () => ({ decisionTypes: [], loading: false }),
}));

// react-markdown is pure ESM and jest 27 can't resolve it (same stub as
// App.test.js). It's only used by DecisionCard, not by this page's header.
jest.mock('react-markdown', () => ({ children }) => <div>{children}</div>);
jest.mock('remark-gfm', () => () => {});

// jsdom has no IntersectionObserver; the page guards on it, but stub it so the
// mobile branch exercises the observer path without crashing.
class MockIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
global.IntersectionObserver = MockIntersectionObserver;

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/relationship/entity/123456789/org/uid-1']}>
      <TranslationProvider>
        <ViewportProvider>
          <Routes>
            <Route
              path="/relationship/entity/:afm/org/:orgUid"
              element={<RelationshipDetailPage />}
            />
          </Routes>
        </ViewportProvider>
      </TranslationProvider>
    </MemoryRouter>
  );

// jsdom's matchMedia stub (setupTests.js) always reports matches: false, so the
// default render takes the desktop branch. For the mobile branch we override
// the stub to report the app's MOBILE_QUERY as matching.
const setMobile = (isMobile) => {
  window.matchMedia = (query) => ({
    matches: isMobile && query === '(max-width: 768px)',
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
};

describe('RelationshipDetailPage entity header', () => {
  afterEach(() => {
    // Restore the setupTests stub so other suites aren't affected.
    setMobile(false);
  });

  test('desktop: renders the top-bar variant, nothing inline', () => {
    setMobile(false);
    renderPage();

    // jsdom has no #top-bar-slot, so TopBarSlot's portal target is missing and
    // the desktop branch renders nothing at all. Assert the branch was taken
    // by checking the inline variant is absent.
    expect(document.querySelector('.relationship-entities-topbar')).toBeNull();
    expect(document.querySelector('.relationship-entities-inline')).toBeNull();
    expect(document.querySelector('.relationship-compact-bar')).toBeNull();
  });

  test('mobile: renders the inline header, no top-bar portal', () => {
    setMobile(true);
    renderPage();

    const inline = document.querySelector('.relationship-entities-inline');
    expect(inline).toBeInTheDocument();
    expect(inline).toHaveClass('relationship-entities');

    expect(document.querySelector('.relationship-entities-topbar')).toBeNull();
    // Compact bar only appears once the inline header scrolls out of view —
    // jsdom never scrolls, so it must not be here yet.
    expect(document.querySelector('.relationship-compact-bar')).toBeNull();

    // Names also appear in the decisions list below, so use getAllByText.
    expect(screen.getAllByText('Test Entity').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Test Org').length).toBeGreaterThan(0);
  });
});
