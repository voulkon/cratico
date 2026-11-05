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
 *   - PARTIAL: partial summary + the summaries that were available
 *   - FAILED: error message, retry button
 *   - SKIPPED: the real reason, plus any shared summaries already available
 *
 * Props:
 *   summary      – { status, skip_reason, summary, items,
 *                    shared_items_available, cost_usd, total_input_tokens,
 *                    total_output_tokens, billed_to, error }
 *   onGenerate   – () => void, called when user clicks generate/regenerate/retry
 *   triggering   – boolean, when true disables the action button
 */
const AISummaryCard = ({ summary, onGenerate, triggering }) => {
  const { t } = useTranslation();

  if (!summary) return null;

  const items = summary.items || [];
  const sharedItemsAvailable = summary.shared_items_available || 0;
  const skipReason = summary.skip_reason;

  const renderItems = () => {
    if (!items.length) return null;
    return (
      <div className="ai-summary-items">
        <div className="ai-summary-items-title">
          {t('notifications.aiSummaryItemsTitle')}
        </div>
        <ul>
          {items.map((item) => (
            <li key={item.decision_id}>
              <span className="ai-summary-item-subject">
                {item.subject || item.ada}
              </span>
              {' — '}
              <span className="ai-summary-item-text">{item.one_liner}</span>
            </li>
          ))}
        </ul>
      </div>
    );
  };

  const renderSharedBlock = () => {
    const hasShared = items.length > 0 || sharedItemsAvailable > 0;
    if (!hasShared) return null;
    return (
      <>
        <p className="ai-summary-shared">
          {t('notifications.aiSummarySharedAvailable', {
            count: items.length || sharedItemsAvailable,
          })}
        </p>
        {renderItems()}
      </>
    );
  };

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
        if (!summary.summary && !items.length) {
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
            {summary.summary && (
              <div className="ai-summary-text">{summary.summary}</div>
            )}
            {renderItems()}
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

      case 'PARTIAL':
        return (
          <div className="ai-summary-completed ai-summary-partial">
            {summary.summary && (
              <div className="ai-summary-text">{summary.summary}</div>
            )}
            <p className="ai-summary-partial-note">
              {t('notifications.aiSummaryPartial')}
            </p>
            {renderItems()}
            <button
              className="ai-summary-btn ai-summary-btn--secondary"
              onClick={onGenerate}
              disabled={triggering}
            >
              {triggering
                ? t('notifications.aiSummaryStarting')
                : t('notifications.aiSummaryRegenerate')}
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

      case 'SKIPPED': {
        const reasonMessage = {
          DAILY_CEILING: t('notifications.aiSummaryCeiling'),
          BUDGET_EXHAUSTED: t('notifications.aiSummaryBudget'),
          USER_DISABLED: t('notifications.aiSummaryUserDisabled'),
          SUBSCRIPTION_DISABLED: t('notifications.aiSummarySubscriptionDisabled'),
          NO_DECISIONS: t('notifications.aiSummaryNoDecisions'),
        }[skipReason] || t('notifications.aiSummarySkipped');
        const hasShared = items.length > 0 || sharedItemsAvailable > 0;

        return (
          <div className="ai-summary-pending">
            <p>{reasonMessage}</p>
            {hasShared ? (
              renderSharedBlock()
            ) : (
              <button
                className="ai-summary-btn ai-summary-btn--primary"
                onClick={onGenerate}
                disabled={triggering}
              >
                {triggering
                  ? t('notifications.aiSummaryStarting')
                  : t('notifications.aiSummaryGenerate')}
              </button>
            )}
          </div>
        );
      }

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
    skip_reason: PropTypes.string,
    summary: PropTypes.string,
    items: PropTypes.arrayOf(
      PropTypes.shape({
        decision_id: PropTypes.number,
        ada: PropTypes.string,
        subject: PropTypes.string,
        one_liner: PropTypes.string,
      })
    ),
    shared_items_available: PropTypes.number,
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
