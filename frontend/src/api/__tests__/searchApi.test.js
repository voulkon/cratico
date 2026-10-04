/**
 * Exact-AFM short-circuit — frontend guards.
 *
 * When the backend entities-fast endpoint returns `exact_afm_match: true`
 * (bare, checksum-valid ΑΦΜ matched directly on AFMEntity.afm), no other
 * search work may happen: the slow document phase must not fire. This is the
 * class of bug caught in logs on 2026-10-04, where the load-more path
 * (searchCategories) fired a stray `searchDocuments(query, 10)` right after
 * an exact-AFM match.
 */
import { streamSearch, searchCategories } from '../searchApi';

jest.mock('../client', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));

const apiClient = require('../client').default;

const ENTITIES_FAST_URL = '/search/entities-fast/';
const DOCUMENTS_URL = '/search/documents/';

const VALID_AFM = '090000045'; // passes the official ΑΦΜ checksum

const exactAfmPayload = {
  data: {
    query: VALID_AFM,
    results: { afm_entities: [{ id: 1, type: 'afmentity', details: { afm: VALID_AFM } }] },
    total_count: 1,
    exact_afm_match: true,
  },
};

const normalPayload = {
  data: { query: 'test', results: { organizations: [] }, total_count: 0 },
};

/** Route apiClient.get by URL prefix. */
const mockRoutes = ({ entities = normalPayload, documents = null } = {}) => {
  apiClient.get.mockImplementation((url) => {
    if (url.startsWith(ENTITIES_FAST_URL)) return Promise.resolve(entities);
    if (url.startsWith(DOCUMENTS_URL)) {
      return Promise.resolve(
        documents || { data: { results: { documents: [] } } }
      );
    }
    return Promise.reject(new Error(`Unexpected URL: ${url}`));
  });
};

const documentsCalls = () =>
  apiClient.get.mock.calls.filter(([url]) => url.startsWith(DOCUMENTS_URL));

/** streamSearch is callback-based; resolve when onDone fires. */
const runStreamSearch = (query, options = {}) =>
  new Promise((resolve, reject) => {
    streamSearch(query, {
      ...options,
      onDone: resolve,
      onError: reject,
    });
  });

beforeEach(() => {
  apiClient.get.mockReset();
});

describe('streamSearch exact-AFM short-circuit', () => {
  it('never calls the documents endpoint when entities-fast returns exact_afm_match', async () => {
    mockRoutes({ entities: exactAfmPayload });

    const done = await runStreamSearch(VALID_AFM, {
      includeDocuments: true,
      limit: 5,
    });

    expect(documentsCalls()).toHaveLength(0);
    expect(done).toEqual({ query: VALID_AFM, exact_afm_match: true });
  });

  it('still runs the document phase for a normal query (control)', async () => {
    mockRoutes();

    await runStreamSearch('δήμος', { includeDocuments: true, limit: 5 });

    expect(documentsCalls()).toHaveLength(1);
  });
});

describe('searchCategories exact-AFM short-circuit', () => {
  it('never calls the documents endpoint when entities-fast returns exact_afm_match', async () => {
    mockRoutes({ entities: exactAfmPayload });

    // Load-more shape: only the extended category is requested (> 0).
    const results = await searchCategories(VALID_AFM, { documents: 10 });

    expect(documentsCalls()).toHaveLength(0);
    expect(results.exact_afm_match).toBe(true);
  });

  it('still fetches documents for a normal query when requested (control)', async () => {
    mockRoutes();

    await searchCategories('δήμος', { organizations: 10, documents: 10 });

    expect(documentsCalls()).toHaveLength(1);
  });
});
