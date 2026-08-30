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

// Client-side cache: models rarely change, so avoid redundant fetches on
// every page navigation.  The list is fetched from 3 places (AI settings,
// decision detail, and once per DecisionCard), so we need to dedupe both
// concurrent callers and full page reloads.
//
// - `_modelsPromise` dedupes in-flight requests: N components mounting at the
//   same time (e.g. a list of decision cards) share ONE network request.
// - `sessionStorage` survives full page reloads (per tab).
// - TTL matches the backend cache (1h).
const _MODELS_CACHE_KEY = 'ai_models_cache_v1';
const _MODELS_CACHE_TTL_MS = 60 * 60 * 1000; // 1h (matches backend)
let _modelsPromise = null; // in-flight request, shared by concurrent callers

const _readModelsCache = () => {
  try {
    const raw = sessionStorage.getItem(_MODELS_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || !parsed.at || (Date.now() - parsed.at) >= _MODELS_CACHE_TTL_MS) {
      sessionStorage.removeItem(_MODELS_CACHE_KEY);
      return null;
    }
    return parsed.data;
  } catch {
    return null;
  }
};

const _writeModelsCache = (data) => {
  try {
    sessionStorage.setItem(
      _MODELS_CACHE_KEY,
      JSON.stringify({ at: Date.now(), data }),
    );
  } catch {
    // ignore (e.g. storage disabled / quota exceeded)
  }
};

export const getAIModels = async () => {
  const cached = _readModelsCache();
  if (cached) return cached;
  if (_modelsPromise) return _modelsPromise;

  _modelsPromise = apiClient
    .get(`${AI_BASE}/models/`)
    .then((response) => {
      _writeModelsCache(response.data);
      return response.data;
    })
    .finally(() => {
      _modelsPromise = null;
    });

  return _modelsPromise;
};

export const syncAIModels = async () => {
  const response = await apiClient.post(`${AI_BASE}/models/sync/`);
  // Invalidate caches so the next list reflects new prices
  try {
    sessionStorage.removeItem(_MODELS_CACHE_KEY);
  } catch {
    // ignore
  }
  return response.data;
};

// ---------------------------------------------------------------------------
// Model preference (independent of API key)
// ---------------------------------------------------------------------------

export const getModelPreference = async () => {
  const response = await apiClient.get(`${AI_BASE}/model-preference/`);
  return response.data;
};

export const updateModelPreference = async (preferredModel, maxTokens) => {
  const payload = {
    preferred_model: preferredModel,
  };
  if (maxTokens !== undefined) {
    payload.max_tokens = maxTokens;
  }
  const response = await apiClient.put(`${AI_BASE}/model-preference/`, payload);
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
