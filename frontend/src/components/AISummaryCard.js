import React from 'react';
import PropTypes from 'prop-types';
import { useTranslation } from '../contexts/TranslationContext';
import './AISummaryCard.css';

/**
 * AISummaryCard — displays the AI summary for a notification batch.
 *
 * Handles all states:
 *   - PENDING: no summary yet, shows generate button
 *   - RUNNING: summary is being generated (spinner)
 *   - COMPLETED: summary text, cost metadata, regenerate button
 *   - FAILED: error message, retry button
 *   - SKIPPED: AI summary disabled for this subscription
 *
 * Props:
 *   summary      – { status, summary, cost_usd, total_input_tokens,
 *                    total_output_tokens, billed_to, error }
 *   onGenerate   – () => void, called when user clicks generate/regenerate/retry
 *   triggering   – boolean, when true disables the action button
 */
const AISummaryCard = ({ summary, onGenerate, triggering }) => {
  const { t } = useTranslation();

  if (!summary) return null;

  const renderContent = () => {
    switch (summary.status) {
      case 'RUNNING':
        return (
          <div className="ai-summary-running">
            <span className="ai-summary-spinner" />
            {' '}
            {t('notifications.aiSummaryRunning')}
          </div>
        );

      case 'COMPLETED':
        if (!summary.summary) {
          // Completed but no content — treat like pending so user can regenerate
          return (
            <div className="ai-summary-pending">
              <p>{t('notifications.aiSummaryNoSummary')}</p>
              <button
                className="ai-summary-btn ai-summary-btn--primary"
                onClick={onGenerate}
                disabled={triggering}
              >
                {triggering ? t('notifications.aiSummaryStarting') : t('notifications.aiSummaryGenerate')}
              </button>
            </div>
          );
        }
        return (
          <div className="ai-summary-completed">
            <div className="ai-summary-text">{summary.summary}</div>
            {summary.cost_usd && (
              <div className="ai-summary-meta">
                {t('notifications.aiSummaryCost')}: ${parseFloat(summary.cost_usd).toFixed(4)}
                {' · '}
                {(summary.total_input_tokens || 0)}+{(summary.total_output_tokens || 0)} {t('notifications.aiSummaryTokens')}
                {' · '}
                {t('notifications.aiSummaryBilled')}: {summary.billed_to || 'SYSTEM'}
              </div>
            )}
            <button
              className="ai-summary-btn ai-summary-btn--secondary"
              onClick={onGenerate}
              disabled={triggering}
            >
              {triggering ? t('notifications.aiSummaryStarting') : t('notifications.aiSummaryRegenerate')}
            </button>
          </div>
        );

      case 'FAILED':
        return (
          <div className="ai-summary-failed">
            <p>{t('notifications.aiSummaryFailed', { error: summary.error || t('common.unknown') })}</p>
            <button
              className="ai-summary-btn ai-summary-btn--secondary"
              onClick={onGenerate}
              disabled={triggering}
            >
              {triggering ? t('notifications.aiSummaryStarting') : t('notifications.aiSummaryRetry')}
            </button>
          </div>
        );

      case 'SKIPPED':
        return (
          <div className="ai-summary-skipped">
            {t('notifications.aiSummarySkipped')}
          </div>
        );

      case 'PENDING':
      default:
        return (
          <div className="ai-summary-pending">
            <p>{t('notifications.aiSummaryNoSummary')}</p>
            <button
              className="ai-summary-btn ai-summary-btn--primary"
              onClick={onGenerate}
              disabled={triggering}
            >
              {triggering ? t('notifications.aiSummaryStarting') : t('notifications.aiSummaryGenerate')}
            </button>
          </div>
        );
    }
  };

  return (
    <div className="ai-summary-card">
      <h3 className="ai-summary-card__title">{t('notifications.aiSummaryTitle')}</h3>
      {renderContent()}
    </div>
  );
};

AISummaryCard.propTypes = {
  summary: PropTypes.shape({
    status: PropTypes.string,
    summary: PropTypes.string,
    cost_usd: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    total_input_tokens: PropTypes.number,
    total_output_tokens: PropTypes.number,
    billed_to: PropTypes.string,
    error: PropTypes.string,
  }),
  onGenerate: PropTypes.func.isRequired,
  triggering: PropTypes.bool,
};

AISummaryCard.defaultProps = {
  summary: null,
  triggering: false,
};

export default AISummaryCard;
