import { useCallback } from 'react';
import apiClient from '../api/client';

/**
 * Hook for decision-level AI operations (extraction + summarization).
 *
 * Returns handlers and the current AI analysis state extracted from the
 * decision object.  The caller is responsible for refreshing the decision
 * after an operation completes (via the returned ``refresh`` callback).
 *
 * Usage:
 *   const { aiAnalysis, requestExtraction, requestAISummary } = useDecisionAI(decision, fetchDecisionData);
 */
export function useDecisionAI(decision, onRefresh) {
  const id = decision?.id;
  const aiAnalysis = decision?.ai_analysis || null;

  const requestExtraction = useCallback(async () => {
    if (!id) return;
    try {
      const response = await apiClient.post(`/ai/decisions/${id}/extract/`);
      if (response.data.status === 'already_extracted') {
        onRefresh?.();
      }
      return response.data;
    } catch (err) {
      throw err.response?.data?.error || err;
    }
  }, [id, onRefresh]);

  const requestAISummary = useCallback(async (force = false) => {
    if (!id) return;
    try {
      const response = await apiClient.post(`/ai/decisions/${id}/summarize/`, force ? { force: true } : {});
      if (response.data.status === 'already_completed') {
        onRefresh?.();
      }
      return response.data;
    } catch (err) {
      throw err.response?.data?.error || err;
    }
  }, [id, onRefresh]);

  return {
    aiAnalysis,
    requestExtraction,
    requestAISummary,
  };
}
