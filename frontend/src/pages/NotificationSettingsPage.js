import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import {
  createNotificationPreference,
  getNotificationPreferences,
  updateNotificationPreference,
} from '../api/notifications';
import './NotificationSettingsPage.css';

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

const DEFAULT_FORM = {
  email_enabled: true,
  email_mode: 'daily_digest',
  digest_hours_local: [8],
  ai_summary_enabled: false,
};

const formatHour = (hour) => `${String(hour).padStart(2, '0')}:00`;

const NotificationSettingsPage = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [preference, setPreference] = useState(null);
  const [form, setForm] = useState(DEFAULT_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useDocumentTitle(t('notificationSettings.title'));

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const rows = await getNotificationPreferences();
        let row = Array.isArray(rows) ? rows[0] : rows;

        if (!row) {
          row = await createNotificationPreference(DEFAULT_FORM);
        }

        if (cancelled) return;
        setPreference(row);
        setForm({
          email_enabled: row.email_enabled,
          email_mode: row.email_mode,
          digest_hours_local:
            row.digest_hours_local && row.digest_hours_local.length
              ? row.digest_hours_local
              : [row.digest_hour_local],
          ai_summary_enabled: row.ai_summary_enabled,
        });
      } catch (err) {
        if (!cancelled) {
          setError(t('notificationSettings.loadError'));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const toggleHour = (hour) => {
    setSaved(false);
    setForm((prev) => {
      const selected = prev.digest_hours_local.includes(hour);
      return {
        ...prev,
        digest_hours_local: selected
          ? prev.digest_hours_local.filter((h) => h !== hour)
          : [...prev.digest_hours_local, hour].sort((a, b) => a - b),
      };
    });
  };

  const handleSave = async () => {
    if (!preference) return;

    const hours = [...form.digest_hours_local]
      .filter((hour) => Number.isInteger(hour) && hour >= 0 && hour <= 23)
      .sort((a, b) => a - b);

    if (form.email_mode !== 'every_run' && hours.length === 0) {
      setError(t('notificationSettings.atLeastOneTime'));
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSaved(false);
      const updated = await updateNotificationPreference(preference.id, {
        ...form,
        digest_hours_local: hours,
      });
      setPreference(updated);
      setForm((prev) => ({ ...prev, digest_hours_local: hours }));
      setSaved(true);
    } catch (err) {
      setError(t('notificationSettings.saveError'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="notification-settings-page">
        <div className="notification-settings-state">
          <div className="loading-spinner" />
          <p>{t('notifications.loadingNotifications')}</p>
        </div>
      </div>
    );
  }

  const showTimes = form.email_mode !== 'every_run';

  return (
    <div className="notification-settings-page">
      <header className="notification-settings-header">
        <div>
          <h1>{t('notificationSettings.title')}</h1>
          <p className="notification-settings-subtitle">
            {t('notificationSettings.subtitle')}
          </p>
        </div>
        <button
          type="button"
          className="notification-settings-back"
          onClick={() => navigate('/notifications')}
        >
          {t('notificationSettings.back')}
        </button>
      </header>

      <section className="notification-settings-card">
        <div className="notification-settings-row">
          <div>
            <h2>{t('notificationSettings.emailEnabled')}</h2>
            <p>{t('notificationSettings.emailEnabledHelp')}</p>
          </div>
          <label className="notification-settings-switch">
            <input
              type="checkbox"
              checked={form.email_enabled}
              onChange={(e) => {
                setSaved(false);
                setForm((prev) => ({
                  ...prev,
                  email_enabled: e.target.checked,
                }));
              }}
            />
            <span />
          </label>
        </div>

        <div className="notification-settings-field">
          <label htmlFor="email-mode">
            {t('notificationSettings.emailMode')}
          </label>
          <select
            id="email-mode"
            value={form.email_mode}
            onChange={(e) => {
              setSaved(false);
              setForm((prev) => ({ ...prev, email_mode: e.target.value }));
            }}
          >
            <option value="every_run">
              {t('notificationSettings.modeEveryRun')}
            </option>
            <option value="daily_digest">
              {t('notificationSettings.modeDaily')}
            </option>
            <option value="weekly_digest">
              {t('notificationSettings.modeWeekly')}
            </option>
          </select>
        </div>

        {showTimes && (
          <div className="notification-settings-field">
            <label>{t('notificationSettings.digestTimes')}</label>
            <p className="notification-settings-help">
              {form.email_mode === 'weekly_digest'
                ? t('notificationSettings.weeklyHelp')
                : t('notificationSettings.digestTimesHelp')}
            </p>
            <div className="notification-hour-grid">
              {HOURS.map((hour) => {
                const selected = form.digest_hours_local.includes(hour);
                return (
                  <button
                    type="button"
                    key={hour}
                    className={`notification-hour${
                      selected ? ' selected' : ''
                    }`}
                    aria-pressed={selected}
                    onClick={() => toggleHour(hour)}
                  >
                    {formatHour(hour)}
                  </button>
                );
              })}
            </div>
            {form.digest_hours_local.length > 0 && (
              <p className="notification-settings-selected">
                {t('notificationSettings.selectedTimes')}:{' '}
                {form.digest_hours_local.map(formatHour).join(', ')}
              </p>
            )}
          </div>
        )}

        {form.email_mode === 'every_run' && (
          <p className="notification-settings-help">
            {t('notificationSettings.everyRunHelp')}
          </p>
        )}

        <div className="notification-settings-row">
          <div>
            <h2>{t('notificationSettings.aiSummaryEnabled')}</h2>
            <p>{t('notificationSettings.aiSummaryEnabledHelp')}</p>
          </div>
          <label className="notification-settings-switch">
            <input
              type="checkbox"
              checked={form.ai_summary_enabled}
              onChange={(e) => {
                setSaved(false);
                setForm((prev) => ({
                  ...prev,
                  ai_summary_enabled: e.target.checked,
                }));
              }}
            />
            <span />
          </label>
        </div>

        {error && <p className="notification-settings-error">{error}</p>}
        {saved && (
          <p className="notification-settings-success">
            {t('notificationSettings.saved')}
          </p>
        )}

        <div className="notification-settings-actions">
          <button
            type="button"
            className="notification-settings-save"
            onClick={handleSave}
            disabled={saving}
          >
            {saving
              ? t('notificationSettings.saving')
              : t('notificationSettings.save')}
          </button>
        </div>
      </section>
    </div>
  );
};

export default NotificationSettingsPage;
