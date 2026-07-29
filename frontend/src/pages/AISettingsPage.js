import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import {
  getAISettings,
  updateAISettings,
  testAIKey,
  getAIModels,
} from '../api/aiApi';
import { formatPrice } from '../utils/format';
import './AISettingsPage.css';

const AISettingsPage = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  useDocumentTitle('AI Settings');

  const [settings, setSettings] = useState(null);
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Form state
  const [provider, setProvider] = useState('OPENROUTER');
  const [apiKey, setApiKey] = useState('');
  const [defaultModel, setDefaultModel] = useState('');
  const [monthlyBudget, setMonthlyBudget] = useState('');
  const [isActive, setIsActive] = useState(true);

  const loadSettings = useCallback(async () => {
    try {
      const data = await getAISettings();
      setSettings(data);
      setProvider(data.provider || 'OPENROUTER');
      setDefaultModel(data.default_model || '');
      setMonthlyBudget(data.monthly_budget_usd || '');
      setIsActive(data.is_active);
    } catch (err) {
      setError(t('aiSettings.loadError'));
    }
  }, [t]);

  const loadModels = useCallback(async () => {
    try {
      const data = await getAIModels();
      setModels(data.models || []);
    } catch (err) {
      // Models might fail if no key is set — that's ok
    }
  }, []);

  useEffect(() => {
    Promise.all([loadSettings(), loadModels()]).finally(() => setLoading(false));
  }, [loadSettings, loadModels]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const data = {
        provider,
        default_model: defaultModel || null,
        monthly_budget_usd: monthlyBudget || null,
        is_active: isActive,
      };
      if (apiKey) {
        data.api_key = apiKey;
      }
      const updated = await updateAISettings(data);
      setSettings(updated);
      setApiKey(''); // Clear the key field after save
      setSuccess(t('aiSettings.saved'));
      // Reload models in case a new key was added
      loadModels();
    } catch (err) {
      setError(err.response?.data?.error || t('aiSettings.saveError'));
    } finally {
      setSaving(false);
    }
  };

  const handleTestKey = async () => {
    setTesting(true);
    setTestResult(null);
    setError(null);
    try {
      const keyToTest = apiKey || null;
      const result = await testAIKey(keyToTest);
      setTestResult(result);
    } catch (err) {
      setTestResult({ is_valid: false, error: t('aiSettings.requestFailed') });
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="ai-settings-page">
        <div className="ai-settings-loading">{t('common.loading')}</div>
      </div>
    );
  }

  return (
    <div className="ai-settings-page">
      <div className="ai-settings-container">
        <h1 className="ai-settings-title">{t('aiSettings.title')}</h1>
        <p className="ai-settings-subtitle">
          {t('aiSettings.subtitle')}
          {!settings?.has_own_key && (
            <span className="ai-settings-note">
              {' '}
              {t('aiSettings.noKeyNote')}
            </span>
          )}
        </p>

        <button
          className="ai-settings-interactions-link"
          onClick={() => navigate('/ai/interactions')}
        >
          {t('aiSettings.viewInteractions')}
        </button>

        {error && <div className="ai-settings-error">{error}</div>}
        {success && <div className="ai-settings-success">{success}</div>}

        {/* Provider */}
        <div className="ai-settings-field">
          <label>{t('aiSettings.provider')}</label>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            disabled
          >
            <option value="OPENROUTER">{t('aiSettings.openRouter')}</option>
            <option value="AWS_BEDROCK" disabled>
              {t('aiSettings.awsBedrockComingSoon')}
            </option>
          </select>
        </div>

        {/* API Key */}
        <div className="ai-settings-field">
          <label>{t('aiSettings.apiKey')}</label>
          <div className="ai-settings-key-row">
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                settings?.api_key_masked
                  ? t('aiSettings.currentKeyMasked', { masked: settings.api_key_masked })
                  : t('aiSettings.enterApiKey')
              }
            />
            <button
              className="ai-settings-test-btn"
              onClick={handleTestKey}
              disabled={testing || (!apiKey && !settings?.has_own_key)}
            >
              {testing ? t('aiSettings.testing') : t('aiSettings.testKey')}
            </button>
          </div>
          {testResult && (
            <div
              className={`ai-settings-test-result ${
                testResult.is_valid ? 'valid' : 'invalid'
              }`}
            >
              {testResult.is_valid ? (
                <>
                  {t('aiSettings.keyValid')}
                  {testResult.limit_total != null && (
                    <span>
                      {' '}
                      {t('aiSettings.credits', {
                        remaining: testResult.limit_remaining,
                        total: testResult.limit_total,
                      })}
                    </span>
                  )}
                </>
              ) : (
                <>{t('aiSettings.keyInvalid')}</>
              )}
            </div>
          )}
        </div>

        {/* Default Model */}
        <div className="ai-settings-field">
          <label>{t('aiSettings.defaultModel')}</label>
          <select
            value={defaultModel}
            onChange={(e) => setDefaultModel(e.target.value)}
          >
            <option value="">{t('aiSettings.selectModel')}</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name || m.id} · {t('aiSettings.ctx')} {(m.context_length / 1000).toFixed(0)}k ·
                ${formatPrice(m.pricing.prompt, t)}/M {t('aiSettings.in')} ·
                ${formatPrice(m.pricing.completion, t)}/M {t('aiSettings.out')}
              </option>
            ))}
          </select>
          {models.length === 0 && (
            <small className="ai-settings-hint">
              {t('aiSettings.noModels')}
            </small>
          )}
        </div>

        {/* Monthly Budget */}
        <div className="ai-settings-field">
          <label>{t('aiSettings.monthlyBudget')}</label>
          <input
            type="number"
            step="0.01"
            value={monthlyBudget}
            onChange={(e) => setMonthlyBudget(e.target.value)}
            placeholder={t('aiSettings.budgetHint').split('.')[0]}
          />
          <small className="ai-settings-hint">
            {t('aiSettings.budgetHint')}
          </small>
        </div>

        {/* Active toggle */}
        <div className="ai-settings-field ai-settings-toggle">
          <label>
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
            />
            {t('aiSettings.active')}
          </label>
        </div>

        {/* Billing info */}
        {settings && (
          <div className="ai-settings-billing">
            <strong>{t('aiSettings.billing')}</strong>{' '}
            {settings.billed_to === 'USER'
              ? t('aiSettings.billedToUser')
              : t('aiSettings.billedToSystem')}
          </div>
        )}

        {/* Save */}
        <button
          className="ai-settings-save-btn"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? t('aiSettings.saving') : t('aiSettings.save')}
        </button>
      </div>
    </div>
  );
};

export default AISettingsPage;
