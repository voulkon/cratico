import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import relationshipsApi from '../api/relationshipsApi';

const DEBOUNCE_MS = 300;

/**
 * Hook to manage top organizations fetching with infinite scroll and search.
 *
 * Mirrors useTopCounterparts but for the entity path (showing top organizations
 * for a given AFM entity).  Handles:
 *  - Paginated fetching (offset-based)
 *  - Debounced search (resets results when query changes)
 *  - Accumulation of results across pages for infinite scroll
 *  - Stable dependency tracking (avoids duplicate fetches from inline objects)
 *
 * @param {string}   afm           - Entity AFM
 * @param {object}   dateRange     - { start_date, end_date }
 * @param {number}   [pageSize=10] - Items per page
 * @param {boolean}  [enabled=true] - When false, no requests are sent
 */
const useTopOrganizations = ({
  afm,
  dateRange,
  pageSize = 10,
  enabled = true,
}) => {
  const [results, setResults] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');

  // Track the current offset so loadMore knows where to continue
  const offsetRef = useRef(0);

  // Debounce the search query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(searchQuery);
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Stabilise dateRange for dependency comparison
  const dateKey = useMemo(
    () => `${dateRange?.start_date ?? ''}|${dateRange?.end_date ?? ''}`,
    [dateRange?.start_date, dateRange?.end_date]
  );

  const fetchPage = useCallback(async (offset, append) => {
    try {
      if (!append) {
        setLoading(true);
        setError(null);
      } else {
        setLoadingMore(true);
      }

      const start = dateRange?.start_date || dateRange?.startDate;
      const end = dateRange?.end_date || dateRange?.endDate;

      const params = {
        start_date: start,
        end_date: end,
        limit: pageSize,
        offset,
      };
      if (debouncedQuery) {
        params.search = debouncedQuery;
      }

      const data = await relationshipsApi.getTopOrganizations(afm, params);

      if (append) {
        setResults(prev => [...prev, ...(data.results || [])]);
      } else {
        setResults(data.results || []);
      }

      setTotalCount(data.pagination?.total_count ?? 0);
      setHasMore(data.pagination?.has_more ?? false);
    } catch (err) {
      console.error('Error fetching top organizations:', err);
      if (!append) setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [afm, dateKey, pageSize, debouncedQuery]);

  // Reset and fetch page 0 when dependencies change
  useEffect(() => {
    if (!enabled || !afm || !dateRange) {
      setResults([]);
      setLoading(false);
      return;
    }

    offsetRef.current = 0;
    setResults([]);
    fetchPage(0, false);
  }, [enabled, afm, dateKey, debouncedQuery, fetchPage]);

  const loadMore = useCallback(() => {
    if (hasMore && !loadingMore && !loading) {
      const nextOffset = offsetRef.current + pageSize;
      offsetRef.current = nextOffset;
      fetchPage(nextOffset, true);
    }
  }, [hasMore, loadingMore, loading, pageSize, fetchPage]);

  const refetch = useCallback(() => {
    offsetRef.current = 0;
    setResults([]);
    fetchPage(0, false);
  }, [fetchPage]);

  return {
    results,
    totalCount,
    hasMore,
    loading,
    loadingMore,
    error,
    loadMore,
    refetch,
    searchQuery,
    setSearchQuery,
  };
};

export default useTopOrganizations;
