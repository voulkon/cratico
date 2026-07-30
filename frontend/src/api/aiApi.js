/**
 * AI API module — endpoints for AI settings, models, interactions, and pipelines.
 */
import apiClient from './client';

const AI_BASE = '/ai';

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export const getAISettings = async () => {
  const response = await apiClient.get(`${AI_BASE}/settings/`);
  return response.data;
};

export const updateAISettings = async (data) => {
  const response = await apiClient.put(`${AI_BASE}/settings/`, data);
  return response.data;
};

export const testAIKey = async (apiKey, rowId = null) => {
  const payload = {};
  if (rowId != null) {
    payload.row_id = rowId;
  } else if (apiKey) {
    payload.api_key = apiKey;
  }
  const response = await apiClient.post(`${AI_BASE}/settings/test-key/`, payload);
  return response.data;
};

// Row-level CRUD for multiple API keys
export const createAISettingsRow = async (data) => {
  const response = await apiClient.post(`${AI_BASE}/settings/rows/`, data);
  return response.data;
};

export const updateAISettingsRow = async (id, data) => {
  const response = await apiClient.put(`${AI_BASE}/settings/rows/${id}/`, data);
  return response.data;
};

export const deleteAISettingsRow = async (id) => {
  await apiClient.delete(`${AI_BASE}/settings/rows/${id}/`);
};

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------

export const getAIModels = async () => {
  const response = await apiClient.get(`${AI_BASE}/models/`);
  return response.data;
};

export const syncAIModels = async () => {
  const response = await apiClient.post(`${AI_BASE}/models/sync/`);
  return response.data;
};

// ---------------------------------------------------------------------------
// Model preference (independent of API key)
// ---------------------------------------------------------------------------

export const getModelPreference = async () => {
  const response = await apiClient.get(`${AI_BASE}/model-preference/`);
  return response.data;
};

export const updateModelPreference = async (preferredModel) => {
  const response = await apiClient.put(`${AI_BASE}/model-preference/`, {
    preferred_model: preferredModel,
  });
  return response.data;
};

// ---------------------------------------------------------------------------
// Interactions
// ---------------------------------------------------------------------------

export const getAIInteractions = async (params = {}) => {
  const response = await apiClient.get(`${AI_BASE}/interactions/`, { params });
  return response.data;
};

export const getAIInteractionsSummary = async (month = null) => {
  const params = month ? { month } : {};
  const response = await apiClient.get(`${AI_BASE}/interactions/summary/`, { params });
  return response.data;
};

export const getAIInteractionDetail = async (id) => {
  const response = await apiClient.get(`${AI_BASE}/interactions/${id}/`);
  return response.data;
};

// ---------------------------------------------------------------------------
// Pipelines
// ---------------------------------------------------------------------------

export const getAIPipelines = async (triggerType = null) => {
  const params = triggerType ? { trigger_type: triggerType } : {};
  const response = await apiClient.get(`${AI_BASE}/pipelines/`, { params });
  return response.data;
};

export const getAIPipelineDetail = async (id) => {
  const response = await apiClient.get(`${AI_BASE}/pipelines/${id}/`);
  return response.data;
};

// ---------------------------------------------------------------------------
// Batch summarization
// ---------------------------------------------------------------------------

export const summarizeBatch = async (batchId) => {
  const response = await apiClient.post(`/notifications/batches/${batchId}/summarize/`);
  return response.data;
};

export const getBatchSummary = async (batchId) => {
  const response = await apiClient.get(`/notifications/batches/${batchId}/summary/`);
  return response.data;
};
