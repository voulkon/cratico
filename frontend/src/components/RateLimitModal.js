import React, { useState, useEffect } from 'react';
import apiClient from '../api/client';
import { useTranslation } from '../contexts/TranslationContext';
import './RateLimitModal.css';

const RateLimitModal = () => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [errorInfo, setErrorInfo] = useState(null);
  const [resetRequested, setResetRequested] = useState(false);
  const [requestLoading, setRequestLoading] = useState(false);
  const [requestError, setRequestError] = useState(null);

  useEffect(() => {
    const handleRateLimitExceeded = (event) => {
      setErrorInfo(event.detail);
      setIsOpen(true);
      // Reset request state when a new rate-limit event fires
      setResetRequested(false);
      setRequestError(null);
    };

    window.addEventListener('rateLimitExceeded', handleRateLimitExceeded);

    return () => {
      window.removeEventListener('rateLimitExceeded', handleRateLimitExceeded);
    };
  }, []);

  const handleRequestReset = async () => {
    setRequestLoading(true);
    setRequestError(null);
    try {
      await apiClient.post('/system/rate-limit/request-reset/');
      setResetRequested(true);
    } catch (err) {
      // Show the server's message, or a generic fallback
      const serverMsg =
        err.response?.data?.message
        || err.response?.data?.error
        || null;

      if (err.response?.status === 401) {
        setRequestError(
          serverMsg || t('rateLimit.loginRequired')
        );
      } else {
        setRequestError(
          serverMsg || t('rateLimit.requestFailed')
        );
      }
    } finally {
      setRequestLoading(false);
    }
  };

  if (!isOpen) return null;

  const timeUntilReset = errorInfo?.resetTime ?
    Math.max(0, Math.ceil((errorInfo.resetTime - new Date()) / 1000 / 60)) : 0;

  return (
    <div className="rate-limit-modal-overlay">
      <div className="rate-limit-modal">
        <div className="modal-header">
          <h3>{t('rateLimit.title')}</h3>
          <button
            className="close-button"
            onClick={() => setIsOpen(false)}
          >
            ×
          </button>
        </div>

        <div className="modal-body">
          <p>{errorInfo?.message}</p>

          {timeUntilReset > 0 && (
            <p>
              {t('rateLimit.resetInMinutes', { minutes: timeUntilReset })}
            </p>
          )}

          {/* ── Reset-request feedback ────────────────────────────── */}
          {resetRequested && (
            <div className="reset-request-confirmation">
              {t('rateLimit.resetRequestSent')}
            </div>
          )}

          {requestError && (
            <div className="reset-request-error">
              {requestError}
            </div>
          )}

          <div className="modal-actions">
            <button
              className="btn btn-primary"
              onClick={() => window.location.href = '/pricing'}
            >
              {t('rateLimit.upgradeSubscription')}
            </button>
            <button
              className="btn btn-outline"
              onClick={handleRequestReset}
              disabled={resetRequested || requestLoading}
            >
              {requestLoading
                ? t('rateLimit.sending')
                : resetRequested
                  ? t('rateLimit.requestSent')
                  : t('rateLimit.requestAdminReset')}
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => setIsOpen(false)}
            >
              {t('rateLimit.continue')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default RateLimitModal;
