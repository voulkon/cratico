import { useState, useEffect, useCallback, useRef } from 'react';
import apiClient from '../api/client';
import { dedupByKey } from '../utils/collectionUtils';

/**
 * Fetch the full set of decision types available for a given context.
 *
 * ⚠️ Always use a dedicated endpoint that scans the ENTIRE queryset for the
 * current context (entity + time range / relationship + time range / temporal).
 * Never derive decision types from a paginated decisions batch — a rare type
 * that only appears past the first page would never be discoverable.
 *
 * The `dedupByKey(..., 'uid')` call below is a defensive layer: the backend
 * groups by `uid`, but this guards against regressions, stale caches, or test
 * payloads. It is a single Map pass and effectively free.
 *
 * @param {string|null} endpoint - Full API path (without query string).
 *                                 When null/empty, the hook is disabled.
 * @param {{startDate: string, endDate: string}|null} dateRange
 * @param {object} [extraParams] - Additional query params merged into the request.
 *                                 Stable across renders if memoized by the caller;
 *                                 otherwise a deep-equality check is used below.
 */
const useDecisionTypes = ({ endpoint, dateRange, extraParams } = {}) => {
  const [decisionTypes, setDecisionTypes] = useState([]);
  const [loading, setLoading] = useState(false);

  // Keep a stable JSON snapshot of extraParams so that a new object literal
  // passed by the caller every render does NOT trigger a refetch. We compare
  // the serialized form and only update the ref when it actually changes.
  const extraParamsRef = useRef(extraParams);
  const extraParamsKey = JSON.stringify(extraParams || {});
  const lastExtraParamsKey = useRef(extraParamsKey);
  if (extraParamsKey !== lastExtraParamsKey.current) {
    lastExtraParamsKey.current = extraParamsKey;
    extraParamsRef.current = extraParams;
  }

  const fetchDecisionTypes = useCallback(async () => {
    if (!endpoint || !dateRange?.startDate || !dateRange?.endDate) return;

    try {
      setLoading(true);
      const params = new URLSearchParams({
        start_date: dateRange.startDate,
        end_date: dateRange.endDate,
        ...(extraParamsRef.current || {}),
      });
      const response = await apiClient.get(`${endpoint}?${params.toString()}`);
      const types = dedupByKey(response.data.decision_types || [], 'uid');
      setDecisionTypes(types);
    } catch (err) {
      console.error('Failed to fetch decision types:', err);
      setDecisionTypes([]);
    } finally {
      setLoading(false);
    }
  }, [endpoint, dateRange?.startDate, dateRange?.endDate, extraParamsKey]);

  useEffect(() => {
    fetchDecisionTypes();
  }, [fetchDecisionTypes]); // eslint-disable-line react-hooks/exhaustive-deps

  return { decisionTypes, loading, refetch: fetchDecisionTypes };
};

export default useDecisionTypes;
