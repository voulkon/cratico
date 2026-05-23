import { useState, useEffect, useCallback } from 'react';
import apiClient from '../api/client';

/**
 * Custom hook to manage decisions fetching, pagination, and loading states
 * Works for entity, AFM entity, temporal, and relationship contexts
 */
const useDecisionsList = ({
  endpoint,
  params = {},
  enabled = true,
  dependencies = []
}) => {
  const [decisions, setDecisions] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  const fetchDecisions = useCallback(async (page = 1, append = false) => {
    if (!enabled) return;

    try {
      if (!append) {
        setLoading(true);
        setError(null);
      } else {
        setLoadingMore(true);
      }

      // Build query parameters
      const queryParams = new URLSearchParams({
        ...params,
        page: page.toString()
      });

      // Remove undefined/null values
      for (const [key, value] of queryParams.entries()) {
        if (value === 'undefined' || value === 'null' || value === '') {
          queryParams.delete(key);
        }
      }

      const response = await apiClient.get(`${endpoint}?${queryParams}`);

      if (append) {
        setDecisions(prev => [...prev, ...response.data.results]);
      } else {
        setDecisions(response.data.results);
      }

      setPagination(response.data.pagination);
    } catch (err) {
      console.error('Error fetching decisions:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [endpoint, params, enabled, ...dependencies]);

  const loadMore = useCallback(() => {
    if (pagination?.has_next && !loadingMore) {
      const nextPage = pagination.current_page + 1;
      fetchDecisions(nextPage, true);
    }
  }, [pagination, loadingMore, fetchDecisions]);

  const refetch = useCallback(() => {
    setDecisions([]);
    fetchDecisions(1, false);
  }, [fetchDecisions]);

  useEffect(() => {
    if (enabled) {
      fetchDecisions(1, false);
    }
  }, [fetchDecisions, enabled]);

  return {
    decisions,
    pagination,
    loading,
    loadingMore,
    error,
    loadMore,
    refetch
  };
};

export default useDecisionsList;
