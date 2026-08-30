import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import TopBarSlot from '../components/TopBarSlot';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import {
  getAISettings,
  updateAISettings,
  testAIKey,
  getAIModels,
  createAISettingsRow,
  updateAISettingsRow,
  deleteAISettingsRow,
  getModelPreference,
  updateModelPreference,
} from '../api/aiApi';
import ModelDropdown from '../components/ModelDropdown';
import './AISettingsPage.css';

const EMPTY_ROW = {
  label: '',
  api_key: '',
  default_model: '',
  monthly_budget_usd: '',
  is_active: true,
};

const AISettingsPage = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  useDocumentTitle('AI Settings');

  // ---------- page-level state ----------
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [saving, setSaving] = useState(false);

  // ---------- data ----------
  const [models, setModels] = useState([]);
  const [rows, setRows] = useState([]);            // all UserAISettings rows
  const [aiEnabled, setAiEnabled] = useState(true);
  const [systemKeyAccepted, setSystemKeyAccepted] = useState(false);
  const [keyMode, setKeyMode] = useState('SYSTEM'); // BYOK | SYSTEM
  const [preferredModel, setPreferredModel] = useState(null); // user's model choice (independent of key)
  const [maxTokens, setMaxTokens] = useState(null);           // user's output-token budget (independent of key)
  const [maxTokensDraft, setMaxTokensDraft] = useState('');   // draft value for the token input

  // ---------- inline "add / edit" form state ----------
  const [editingRow, setEditingRow] = useState(null); // null | row-id | 'new'
  const [form, setForm] = useState({ ...EMPTY_ROW });
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);

  // ---------- per-row test state (for existing keys in display mode) ----------
  const [rowTestResults, setRowTestResults] = useState({});  // { [rowId]: result }
  const [rowTesting, setRowTesting] = useState({});            // { [rowId]: bool }

  // ---------- load ----------
  const loadAll = useCallback(async () => {
    try {
      const data = await getAISettings();
      setRows(data.rows || []);
      setAiEnabled(data.ai_enabled ?? true);
      setSystemKeyAccepted(data.ai_system_key_accepted ?? false);
      setKeyMode(data.key_mode || 'SYSTEM');
      // Load model preference (independent endpoint)
      try {
        const pref = await getModelPreference();
        setPreferredModel(pref.preferred_model || null);
        setMaxTokens(pref.max_tokens ?? null);
        setMaxTokensDraft(pref.max_tokens ?? '');
      } catch {
        // non-critical — model preference might not be available yet
      }
    } catch (err) {
      setError(t('aiSettings.loadError'));
    }
  }, [t]);

  const loadModels = useCallback(async () => {
    try {
      const data = await getAIModels();
      setModels(data.models || []);
    } catch {
      // non-critical
    }
  }, []);

  useEffect(() => {
    Promise.all([loadAll(), loadModels()]).finally(() => setLoading(false));
  }, [loadAll, loadModels]);

  // ---------- helpers ----------
  const clearMessages = () => { setError(null); setSuccess(null); };

  const hasActiveByok = rows.some((r) => r.has_own_key);

  // ---------- master AI toggle ----------
  const handleToggleAI = async () => {
    clearMessages();
    const next = !aiEnabled;
    try {
      await updateAISettings({ ai_enabled: next });
      setAiEnabled(next);
      setSuccess(t('aiSettings.saved'));
    } catch (err) {
      setError(err.response?.data?.error || t('aiSettings.saveError'));
    }
  };

  // ---------- model preference (independent of key) ----------
  const handleModelChange = async (modelId) => {
    clearMessages();
    try {
      await updateModelPreference(modelId || null);
      setPreferredModel(modelId || null);
      setSuccess(t('aiSettings.saved'));
    } catch (err) {
      setError(err.response?.data?.error || t('aiSettings.saveError'));
    }
  };
  const handleMaxTokensSave = async () => {
    clearMessages();
    let parsed = null;
    const raw = String(maxTokensDraft).trim();
    if (raw !== '') {
      parsed = Number(raw);
      if (!Number.isInteger(parsed) || parsed <= 0) {
        setError(t('aiSettings.maxTokensInvalid'));
        setMaxTokensDraft(maxTokens ?? '');
        return;
      }
    }
    try {
      await updateModelPreference(preferredModel || null, parsed);
      setMaxTokens(parsed);
      setMaxTokensDraft(parsed ?? '');
      setSuccess(t('aiSettings.saved'));
    } catch (err) {
      setError(err.response?.data?.error || t('aiSettings.saveError'));
    }
  };
  const handleAcceptSystemKey = async () => {
    clearMessages();
    try {
      await updateAISettings({ ai_system_key_accepted: true });
      setSystemKeyAccepted(true);
      setSuccess(t('aiSettings.saved'));
    } catch (err) {
      setError(err.response?.data?.error || t('aiSettings.saveError'));
    }
  };

  // ---------- row CRUD ----------
  const startAdd = () => {
    setEditingRow('new');
    setForm({ ...EMPTY_ROW });
    setTestResult(null);
  };

  const startEdit = (row) => {
    setEditingRow(row.id);
    setForm({
      label: row.label || '',
      api_key: '',
      default_model: row.default_model || '',
      monthly_budget_usd: row.monthly_budget_usd || '',
      is_active: row.is_active,
    });
    setTestResult(null);
  };

  const cancelEdit = () => {
    setEditingRow(null);
    setForm({ ...EMPTY_ROW });
    setTestResult(null);
  };

  const handleTestKey = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testAIKey(form.api_key || null);
      setTestResult(result);
    } catch {
      setTestResult({ is_valid: false, error: t('aiSettings.requestFailed') });
    } finally {
      setTesting(false);
    }
  };

  const handleSaveRow = async () => {
    setSaving(true);
    clearMessages();
    try {
      const payload = {
        label: form.label,
        default_model: form.default_model || null,
        monthly_budget_usd: form.monthly_budget_usd || null,
        is_active: form.is_active,
      };
      if (form.api_key) payload.api_key = form.api_key;

      if (editingRow === 'new') {
        await createAISettingsRow(payload);
      } else {
        await updateAISettingsRow(editingRow, payload);
      }
      cancelEdit();
      await loadAll();
      await loadModels();
      setSuccess(t('aiSettings.saved'));
    } catch (err) {
      setError(err.response?.data?.error || t('aiSettings.saveError'));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteRow = async (rowId) => {
    if (!window.confirm(t('aiSettings.confirmDeleteKey'))) return;
    clearMessages();
    try {
      await deleteAISettingsRow(rowId);
      await loadAll();
      setSuccess(t('aiSettings.keyDeleted'));
    } catch (err) {
      setError(err.response?.data?.error || t('aiSettings.saveError'));
    }
  };

  const handleMakeDefault = async (rowId) => {
    clearMessages();
    try {
      await updateAISettingsRow(rowId, { is_default: true });
      await loadAll();
      setSuccess(t('aiSettings.saved'));
    } catch (err) {
      setError(err.response?.data?.error || t('aiSettings.saveError'));
    }
  };

  const handleTestExistingKey = async (rowId) => {
    setRowTesting((prev) => ({ ...prev, [rowId]: true }));
    setRowTestResults((prev) => ({ ...prev, [rowId]: null }));
    try {
      const result = await testAIKey(null, rowId);
      setRowTestResults((prev) => ({ ...prev, [rowId]: result }));
    } catch {
      setRowTestResults((prev) => ({
        ...prev,
        [rowId]: { is_valid: false, error: t('aiSettings.requestFailed') },
      }));
    } finally {
      setRowTesting((prev) => ({ ...prev, [rowId]: false }));
    }
  };

  // ---------- render ----------
  if (loading) {
    return (
      <div className="ai-settings-page">
        <div className="ai-settings-loading">{t('common.loading')}</div>
      </div>
    );
  }

  const disabled = !aiEnabled;

  return (
    <div className="ai-settings-page">
      {/* ── Title rendered into the fixed top bar via portal ──── */}
      <TopBarSlot>
        <div className="ai-settings-topbar">
          <span className="ai-settings-title-topbar">{t('aiSettings.title')}</span>
        </div>
      </TopBarSlot>

      <div className="ai-settings-container">
        <p className="ai-settings-subtitle">{t('aiSettings.subtitle')}</p>

        <button
          className="ai-settings-interactions-link"
          onClick={() => navigate('/ai/interactions')}
        >
          {t('aiSettings.viewInteractions')}
        </button>

        {error && <div className="ai-settings-error">{error}</div>}
        {success && <div className="ai-settings-success">{success}</div>}

        {/* ================================================================ */}
        {/*  PART 1 — Master AI toggle                                        */}
        {/* ================================================================ */}
        <div className={`ai-card ${disabled ? 'ai-card--disabled' : ''}`}>
          <div className="ai-card-header">
            <div className="ai-card-header-left">
              <h2 className="ai-card-title">{t('aiSettings.aiFeatures')}</h2>
              <p className="ai-card-desc">{t('aiSettings.aiFeaturesDesc')}</p>
            </div>
            <label className="ai-toggle">
              <input
                type="checkbox"
                checked={aiEnabled}
                onChange={handleToggleAI}
              />
              <span className="ai-toggle-slider" />
            </label>
          </div>
        </div>

        {/* ================================================================ */}
        {/*  PART 2 — Preferred Model (independent of key)                     */}
        {/* ================================================================ */}
        <div className={`ai-card ${disabled ? 'ai-card--disabled' : ''}`}>
          <div className="ai-card-header">
            <div className="ai-card-header-left">
              <h2 className="ai-card-title">{t('aiSettings.preferredModel')}</h2>
              <p className="ai-card-desc">
                {t('aiSettings.preferredModelDesc')}
              </p>
            </div>
          </div>
          <div className="ai-model-preference-row">
            <ModelDropdown
              models={models}
              value={preferredModel || ''}
              onChange={handleModelChange}
              disabled={disabled}
              t={t}
            />
            {preferredModel && (
              <span className="ai-model-preference-badge">
                {t('aiSettings.usingModel', { model: preferredModel })}
              </span>
            )}
          </div>
          <div className="ai-model-preference-row ai-max-tokens-row">
            <label className="ai-max-tokens-label" htmlFor="max-tokens-input">
              {t('aiSettings.maxTokens')}
            </label>
            <input
              id="max-tokens-input"
              className="ai-max-tokens-input"
              type="number"
              min="1"
              step="100"
              value={maxTokensDraft}
              onChange={(e) => setMaxTokensDraft(e.target.value)}
              onBlur={handleMaxTokensSave}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleMaxTokensSave();
                }
              }}
              placeholder={t('aiSettings.maxTokensPlaceholder')}
              disabled={disabled}
            />
          </div>
          <p className="ai-card-desc">{t('aiSettings.maxTokensDesc')}</p>
        </div>

        {/* ================================================================ */}
        {/*  PART 3 — BYOK: Your API Keys                                      */}
        {/* ================================================================ */}
        <div className={`ai-card ${disabled ? 'ai-card--disabled' : ''}`}>
          <div className="ai-card-header">
            <div className="ai-card-header-left">
              <h2 className="ai-card-title">{t('aiSettings.yourKeys')}</h2>
              <p className="ai-card-desc">
                {keyMode === 'BYOK'
                  ? t('aiSettings.byokActive')
                  : t('aiSettings.byokInactive')}
              </p>
            </div>
            {!disabled && (
              <button className="ai-btn ai-btn--primary" onClick={startAdd}>
                + {t('aiSettings.addKey')}
              </button>
            )}
          </div>

          {/* --- key list --- */}
          {rows.length === 0 && !editingRow && (
            <p className="ai-card-empty">{t('aiSettings.noKeysYet')}</p>
          )}

          <div className="ai-keys-list">
            {rows.map((row) => (
              <div
                key={row.id}
                className={`ai-key-item ${row.is_default ? 'ai-key-item--default' : ''}`}
              >
                {editingRow === row.id ? (
                  /* ---- inline edit form ---- */
                  <KeyForm
                    form={form}
                    setForm={setForm}
                    models={models}
                    testResult={testResult}
                    testing={testing}
                    onTest={handleTestKey}
                    onSave={handleSaveRow}
                    onCancel={cancelEdit}
                    saving={saving}
                    t={t}
                  />
                ) : (
                  /* ---- display row ---- */
                  <>
                    <div className="ai-key-meta">
                      {row.is_default && (
                        <span className="ai-badge">{t('aiSettings.default')}</span>
                      )}
                      <span className="ai-key-label">
                        {row.label || t('aiSettings.unnamedKey')}
                      </span>
                      <span className="ai-key-masked">
                        {row.api_key_masked || t('aiSettings.noKeyStored')}
                      </span>
                      <span className={`ai-key-status ${row.is_active ? 'ai-key-status--active' : ''}`}>
                        {row.is_active ? t('aiSettings.active') : t('aiSettings.inactive')}
                      </span>
                    </div>
                    <div className="ai-key-details">
                      {row.default_model && (
                        <span>{t('aiSettings.model')}: {row.default_model}</span>
                      )}
                      {row.monthly_budget_usd && (
                        <span>{t('aiSettings.budget')}: ${row.monthly_budget_usd}</span>
                      )}
                      <span>{t('aiSettings.billing')} {row.billed_to === 'USER' ? t('aiSettings.billedToUser') : t('aiSettings.billedToSystem')}</span>
                    </div>
                    {/* per-row test result */}
                    {rowTestResults[row.id] && (
                      <div
                        className={`ai-settings-test-result ${
                          rowTestResults[row.id].is_valid ? 'valid' : 'invalid'
                        }`}
                      >
                        {rowTestResults[row.id].is_valid ? (
                          <>
                            {t('aiSettings.keyValid')}
                            {rowTestResults[row.id].limit_total != null && (
                              <span>
                                {' '}
                                {t('aiSettings.credits', {
                                  remaining: rowTestResults[row.id].limit_remaining,
                                  total: rowTestResults[row.id].limit_total,
                                })}
                              </span>
                            )}
                          </>
                        ) : (
                          <>✗ {rowTestResults[row.id].error || t('aiSettings.keyInvalid')}</>
                        )}
                      </div>
                    )}
                    <div className="ai-key-actions">
                      {!row.is_default && (
                        <button
                          className="ai-btn ai-btn--ghost"
                          onClick={() => handleMakeDefault(row.id)}
                          disabled={disabled}
                        >
                          {t('aiSettings.makeDefault')}
                        </button>
                      )}
                      <button
                        className="ai-btn ai-btn--ghost"
                        onClick={() => startEdit(row)}
                        disabled={disabled}
                      >
                        {t('aiSettings.edit')}
                      </button>
                      <button
                        className="ai-btn ai-btn--ghost"
                        onClick={() => handleTestExistingKey(row.id)}
                        disabled={disabled || rowTesting[row.id]}
                      >
                        {rowTesting[row.id] ? t('aiSettings.testing') : t('aiSettings.testKey')}
                      </button>
                      <button
                        className="ai-btn ai-btn--ghost ai-btn--danger"
                        onClick={() => handleDeleteRow(row.id)}
                        disabled={disabled}
                      >
                        {t('aiSettings.delete')}
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}

            {/* ---- new-key inline form ---- */}
            {editingRow === 'new' && (
              <div className="ai-key-item ai-key-item--new">
                <KeyForm
                  form={form}
                  setForm={setForm}
                  models={models}
                  testResult={testResult}
                  testing={testing}
                  onTest={handleTestKey}
                  onSave={handleSaveRow}
                  onCancel={cancelEdit}
                  saving={saving}
                  t={t}
                />
              </div>
            )}
          </div>
        </div>

        {/* ================================================================ */}
        {/*  PART 4 — System Key acknowledgment                                */}
        {/* ================================================================ */}
        {!hasActiveByok && (
          <div className={`ai-card ${disabled ? 'ai-card--disabled' : ''}`}>
            <div className="ai-card-header">
              <div className="ai-card-header-left">
                <h2 className="ai-card-title">{t('aiSettings.systemKey')}</h2>
                <p className="ai-card-desc">
                  {t('aiSettings.systemKeyDesc')}
                </p>
              </div>
            </div>
            {!systemKeyAccepted ? (
              <div className="ai-system-key-prompt">
                <p>{t('aiSettings.systemKeyPrompt')}</p>
                <button
                  className="ai-btn ai-btn--primary"
                  onClick={handleAcceptSystemKey}
                  disabled={disabled}
                >
                  {t('aiSettings.acceptSystemKey')}
                </button>
              </div>
            ) : (
              <div className="ai-system-key-accepted">
                <span className="ai-check-icon">✓</span>
                {t('aiSettings.systemKeyAccepted')}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/*  Inline key-editing form (shared between add & edit)                */
/* ------------------------------------------------------------------ */
const KeyForm = ({ form, setForm, models, testResult, testing, onTest, onSave, onCancel, saving, t }) => {
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  return (
    <div className="ai-key-form">
      <div className="ai-key-form-row">
        <label>{t('aiSettings.label')}</label>
        <input
          type="text"
          value={form.label}
          onChange={set('label')}
          placeholder={t('aiSettings.labelPlaceholder')}
        />
      </div>

      <div className="ai-key-form-row">
        <label>{t('aiSettings.apiKey')}</label>
        <div className="ai-settings-key-row">
          <input
            type="password"
            value={form.api_key}
            onChange={set('api_key')}
            placeholder={t('aiSettings.enterApiKey')}
          />
          <button
            type="button"
            className="ai-settings-test-btn"
            onClick={onTest}
            disabled={testing || !form.api_key}
          >
            {testing ? t('aiSettings.testing') : t('aiSettings.testKey')}
          </button>
        </div>
        {testResult && (
          <div className={`ai-settings-test-result ${testResult.is_valid ? 'valid' : 'invalid'}`}>
            {testResult.is_valid
              ? `${t('aiSettings.keyValid')}${testResult.limit_total != null ? ` — ${t('aiSettings.credits', { remaining: testResult.limit_remaining, total: testResult.limit_total })}` : ''}`
              : `${t('aiSettings.keyInvalid')}`}
          </div>
        )}
      </div>

      <div className="ai-key-form-row">
        <label>{t('aiSettings.defaultModel')}</label>
        <ModelDropdown
          models={models}
          value={form.default_model}
          onChange={(id) => setForm((f) => ({ ...f, default_model: id }))}
          placeholder={t('aiSettings.selectModel')}
          t={t}
        />
      </div>

      <div className="ai-key-form-row">
        <label>{t('aiSettings.monthlyBudget')}</label>
        <input
          type="number"
          step="0.01"
          value={form.monthly_budget_usd}
          onChange={set('monthly_budget_usd')}
          placeholder="0.00"
        />
        <small className="ai-settings-hint">{t('aiSettings.budgetHint')}</small>
      </div>

      <div className="ai-key-form-row ai-key-form-toggle">
        <label>
          <input
            type="checkbox"
            checked={form.is_active}
            onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
          />
          {t('aiSettings.active')}
        </label>
      </div>

      <div className="ai-key-form-actions">
        <button className="ai-btn ai-btn--primary" onClick={onSave} disabled={saving}>
          {saving ? t('aiSettings.saving') : t('aiSettings.save')}
        </button>
        <button className="ai-btn ai-btn--ghost" onClick={onCancel}>
          {t('aiSettings.cancel')}
        </button>
      </div>
    </div>
  );
};

export default AISettingsPage;
