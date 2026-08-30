import { useCallback } from 'react';
import apiClient from '../api/client';

/**
 * Hook for decision-level AI operations (extraction + summarization).
 *
 * Returns handlers and the current AI analyses array extracted from the
 * decision object.  Supports multiple summaries per decision (one per model).
 *
 * Usage:
 *   const { aiAnalyses, requestExtraction, requestAISummary } = useDecisionAI(decision, fetchDecisionData);
 */
export function useDecisionAI(decision, onRefresh) {
  const id = decision?.id;
  // Support both old ai_analysis (single) and new ai_analyses (array)
  const aiAnalyses = decision?.ai_analyses || (decision?.ai_analysis ? [decision.ai_analysis] : []);

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

  const requestAISummary = useCallback(async (force = false, model = null) => {
    if (!id) return;
    try {
      const payload = force ? { force: true } : {};
      if (model) {
        payload.model = model;
      }
      const response = await apiClient.post(`/ai/decisions/${id}/summarize/`, payload);
      if (response.data.status === 'already_completed') {
        onRefresh?.();
      }
      return response.data;
    } catch (err) {
      throw err.response?.data?.error || err;
    }
  }, [id, onRefresh]);

  const requestAmountVerification = useCallback(async (dryRun = false) => {
    if (!id) return;
    try {
      const response = await apiClient.post(
        `/ai/decisions/${id}/verify-amount/`,
        dryRun ? { dry_run: true } : {}
      );
      return response.data;
    } catch (err) {
      throw err.response?.data?.error || err;
    }
  }, [id]);

  return {
    aiAnalyses,
    requestExtraction,
    requestAISummary,
    requestAmountVerification,
  };
}
