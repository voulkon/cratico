import { useState, useEffect, useCallback, useRef } from 'react';
import apiClient from '../api/client';

/**
 * Unified hook to manage decisions fetching, pagination, and loading states.
 *
 * Works for all decision-list contexts:
 *   - entity pages   (org/signer/unit/afm)
 *   - temporal exploration
 *   - relationship pages
 *   - notification batch / subscription history
 *
 * @param {string}   endpoint              - API path (e.g. "/entity/afm/123/decisions/")
 * @param {object}   params                - Stable query-param bag.  Only the
 *                                           serialised JSON is used for diffing,
 *                                           so inline objects are safe.
 * @param {boolean}  enabled               - When false, no request is sent
 * @param {number}   [pageSize=20]         - Items per page
 */
const useDecisionsList = ({
  endpoint,
  params = {},
  enabled = true,
  pageSize = 20,
}) => {
  const [decisions, setDecisions] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  // Stabilise the params object by comparing its JSON form, so inline
  // objects passed from JSX don't cause infinite re-fetches.
  const paramsKey = JSON.stringify(params);
  const prevParamsKey = useRef(paramsKey);

  // Build a stable query-string from the params bag
  const buildQueryString = useCallback((page) => {
    const qs = new URLSearchParams({
      ...params,
      page: page.toString(),
      page_size: pageSize.toString(),
    });
    // Drop empty / undefined / null values
    for (const [key, value] of qs.entries()) {
      if (value === 'undefined' || value === 'null' || value === '') {
        qs.delete(key);
      }
    }
    return qs.toString();
  }, [paramsKey, pageSize]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchPage = useCallback(async (page, append) => {
    try {
      if (!append) {
        setLoading(true);
        setError(null);
      } else {
        setLoadingMore(true);
      }

      const qs = buildQueryString(page);
      const response = await apiClient.get(`${endpoint}?${qs}`);

      if (append) {
        setDecisions(prev => [...prev, ...(response.data.results || [])]);
      } else {
        setDecisions(response.data.results || []);
      }

      setPagination(response.data.pagination);
    } catch (err) {
      console.error('Error fetching decisions:', err);
      if (!append) setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [endpoint, buildQueryString]);

  // When params change (or enabled toggles on), refetch page 1
  useEffect(() => {
    if (!enabled) return;

    // If the serialised params haven't changed, skip (e.g. inline object
    // with identical keys/values on re-render).
    const changed = paramsKey !== prevParamsKey.current;
    prevParamsKey.current = paramsKey;

    if (!changed && decisions.length > 0) return; // not a fresh mount

    setDecisions([]);
    fetchPage(1, false);
  }, [enabled, paramsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadMore = useCallback(() => {
    if (pagination?.has_next && !loadingMore) {
      fetchPage(pagination.current_page + 1, true);
    }
  }, [pagination, loadingMore, fetchPage]);

  const refetch = useCallback(() => {
    setDecisions([]);
    fetchPage(1, false);
  }, [fetchPage]);

  return {
    decisions,
    pagination,
    loading,
    loadingMore,
    error,
    loadMore,
    refetch,
  };
};

export default useDecisionsList;
