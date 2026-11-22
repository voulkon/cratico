import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { TranslationProvider } from '../../contexts/TranslationContext';
import DecisionCard from '../DecisionCard';

jest.mock('../../api/client', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
}));
const apiClient = require('../../api/client').default;

jest.mock('../../api/aiApi', () => ({
  __esModule: true,
  getAIModels: jest.fn(),
}));
const { getAIModels } = require('../../api/aiApi');

// react-markdown / remark-gfm are pure ESM and jest 27 can't resolve them.
jest.mock('react-markdown', () => ({ children }) => <div>{children}</div>);
jest.mock('remark-gfm', () => () => {});

const BASE_DECISION = {
  id: 123,
  ada: 'ADA123',
  subject: 'Test decision',
  issue_date: '2026-01-01',
  amount: 100,
  decision_type: { uid: 'Δ1', label: 'Type' },
  organization: { uid: '100', label: 'Org' },
  signers: [],
  kae_amounts: [],
  has_document_content: true,
  one_liner: null,
  ai_analyses: [
    {
      id: 7,
      status: 'COMPLETED',
      summary: 'Seeded summary.',
      model_used: 'seeded/model',
      cost_usd: null,
    },
  ],
};

const makeDecision = (overrides = {}) => ({ ...BASE_DECISION, ...overrides });

const renderCard = (decision = makeDecision()) =>
  render(
    <MemoryRouter>
      <TranslationProvider>
        <DecisionCard
          decision={decision}
          formatAmount={(value) => String(value)}
          index={0}
          isLastItem
        />
      </TranslationProvider>
    </MemoryRouter>
  );

const openSection = (container, selector) => {
  const el = container.querySelector(selector);
  expect(el).not.toBeNull();
  el.open = true;
  fireEvent(el, new Event('toggle'));
};

const calledWith = (url) =>
  apiClient.get.mock.calls.some(([requested]) => requested === url);

beforeEach(() => {
  // Never resolves: the model list is unrelated to these tests, and a
  // resolved promise would schedule a state update outside act().
  getAIModels.mockReturnValue(new Promise(() => {}));
  apiClient.get.mockReset();
  apiClient.get.mockImplementation((url) => {
    if (url === '/decisions/123/content/') {
      return Promise.resolve({
        data: {
          status: 'COMPLETED',
          raw_text: 'Extracted body.',
          character_count: 15,
          page_count: 1,
          extraction_provider: 'PYMUPDF',
          processing_time_ms: 12,
        },
      });
    }
    if (url === '/decisions/123/') {
      return Promise.resolve({
        data: {
          ai_analyses: [
            {
              id: 8,
              status: 'COMPLETED',
              summary: 'Fresh summary.',
              model_used: 'fresh/model',
              cost_usd: null,
            },
          ],
        },
      });
    }
    return Promise.resolve({ data: {} });
  });
});

describe('DecisionCard lazy detail loading', () => {
  test('collapsed cards make no detail or content request on mount', () => {
    renderCard();

    expect(calledWith('/decisions/123/')).toBe(false);
    expect(calledWith('/decisions/123/content/')).toBe(false);
  });

  test('seeds AI summaries from the list payload without a fetch', () => {
    renderCard();

    // The completed analysis rides the list row, so it renders immediately.
    expect(screen.getByText('seeded/model')).toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  test('expanding the AI section fetches the detail exactly once', async () => {
    const { container } = renderCard();

    openSection(container, 'details.dc-ai-collapsible');

    await waitFor(() => expect(calledWith('/decisions/123/')).toBe(true));
    await waitFor(() => expect(screen.getByText('fresh/model')).toBeInTheDocument());
    expect(
      apiClient.get.mock.calls.filter(([url]) => url === '/decisions/123/')
    ).toHaveLength(1);
  });

  test('expanding the document section fetches content on demand', async () => {
    const { container } = renderCard();

    expect(calledWith('/decisions/123/content/')).toBe(false);

    openSection(container, 'details.dc-content-collapsible');

    await waitFor(() =>
      expect(calledWith('/decisions/123/content/')).toBe(true)
    );
    await waitFor(() =>
      expect(screen.getByText('Extracted body.')).toBeInTheDocument()
    );
  });

  test('does not fetch content when the row has none', () => {
    const { container } = renderCard(
      makeDecision({ has_document_content: false, ai_analyses: [] })
    );

    openSection(container, 'details.dc-content-collapsible');

    expect(calledWith('/decisions/123/content/')).toBe(false);
  });
});
