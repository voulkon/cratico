import React from 'react';
import PropTypes from 'prop-types';
import { useTranslation } from '../contexts/TranslationContext';
import { formatDate } from '../utils/dateUtils';
import CollapsibleCard from './CollapsibleCard';
import { AlertIcon, LoaderIcon, SparklesIcon } from './Icons';
import './DecisionAICards.css';

/**
 * OneLinerAttemptsCard — history of one-liner generation attempts.
 *
 * Shows running/pending, completed (newest first, with the current default
 * marked) and failed attempts, plus a button to force a fresh attempt.
 *
 * Props:
 *   attempts             – [{ id, attempt, status, model, one_liner,
 *                             prompt_kind, extraction_provider, cost_usd,
 *                             completed_at, error_message }]
 *   defaultOneLinerId    – id of the currently selected one-liner
 *   onRegenerate         – () => void
 *   requesting           – true while the request is in flight
 */
const OneLinerAttemptsCard = ({
  attempts,
  defaultOneLinerId,
  onRegenerate,
  requesting,
}) => {
  const { t } = useTranslation();

  const pending = attempts.filter(
    (a) => a.status === 'RUNNING' || a.status === 'PENDING'
  );
  const completed = attempts.filter((a) => a.status === 'COMPLETED' && a.one_liner);
  const failed = attempts.filter((a) => a.status === 'FAILED');

  return (
    <CollapsibleCard
      title={
        <span className="ai-analysis-title">
          <SparklesIcon size={16} /> {t('decisionDetail.oneLinerAttempts', 'One-liner attempts')}
          {attempts.length > 0 && (
            <span className="ai-analysis-count"> ({attempts.length})</span>
          )}
        </span>
      }
      subtitle={
        pending.length > 0 ? (
          <span className="ai-analysis-subtitle">
            {t('decisionDetail.oneLinerRunning', 'Generating one-liner…')}
          </span>
        ) : null
      }
      badge={
        pending.length > 0 ? (
          <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
        ) : null
      }
      defaultOpen={false}
      className="ai-analysis-collapsible"
    >
      <div className="ai-analysis-request-row">
        <button
          className="document-link ai-summary-retry"
          onClick={onRegenerate}
          disabled={requesting}
          title={t('decisionDetail.regenerateOneLinerHint', 'Generates a fresh attempt under the current circumstances')}
        >
          {requesting ? <LoaderIcon className="spinner" size={14} /> : <SparklesIcon size={14} />}
          {' '}{t('decisionDetail.regenerateOneLiner', 'Regenerate one-liner')}
        </button>
      </div>

      {/* Running / pending attempts */}
      {pending.map((a) => (
        <div key={`ol-running-${a.id}`} className="ai-summary-item ai-summary-item--running">
          <div className="ai-summary-item-header">
            <span className="ai-model-badge">{a.model || t('decisionCard.defaultModel')}</span>
            <div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
          </div>
          <p className="ai-summary-item-status">
            #{a.attempt} · {t('decisionDetail.oneLinerRunning', 'Generating one-liner…')}
          </p>
        </div>
      ))}

      {/* Completed attempts — newest first */}
      {completed.map((a) => {
        const isDefault = defaultOneLinerId === a.id;
        return (
          <div key={`ol-${a.id}`} className="ai-summary-item">
            <div className="ai-summary-item-header">
              <span className="ai-model-badge">
                #{a.attempt} {a.model || t('decisionCard.defaultModel')}
                {isDefault && (
                  <span title={t('decisionDetail.oneLinerDefault', 'Current one-liner')}> ★</span>
                )}
              </span>
              <span className="ai-summary-item-cost">
                {a.prompt_kind && `${a.prompt_kind}`}
                {a.extraction_provider && ` · ${a.extraction_provider}`}
                {a.cost_usd && ` · $${a.cost_usd}`}
                {a.completed_at && ` · ${formatDate(a.completed_at)}`}
              </span>
            </div>
            <div className="ai-summary-text one-liner-text">{a.one_liner}</div>
          </div>
        );
      })}

      {/* Failed attempts */}
      {failed.map((a) => (
        <div key={`ol-failed-${a.id}`} className="ai-summary-item ai-summary-item--failed">
          <div className="ai-summary-item-header">
            <span className="ai-model-badge">
              #{a.attempt} {a.model || t('decisionCard.defaultModel')}
            </span>
            <AlertIcon size={14} />
          </div>
          <p className="ai-summary-item-error">
            {a.error_message || t('decisionDetail.oneLinerFailed', 'Η δημιουργία σύνοψης απέτυχε')}
          </p>
        </div>
      ))}

      {/* No attempts yet */}
      {attempts.length === 0 && (
        <div className="ai-summary-placeholder">
          <SparklesIcon size={20} />
          <p>{t('decisionDetail.noOneLiners', 'No one-liner attempts yet — generate one from a notification batch or with the button above.')}</p>
        </div>
      )}
    </CollapsibleCard>
  );
};

OneLinerAttemptsCard.propTypes = {
  attempts: PropTypes.arrayOf(PropTypes.shape({
    id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    attempt: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    status: PropTypes.string,
    model: PropTypes.string,
    one_liner: PropTypes.string,
    prompt_kind: PropTypes.string,
    extraction_provider: PropTypes.string,
    cost_usd: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    completed_at: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    error_message: PropTypes.string,
  })),
  defaultOneLinerId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  onRegenerate: PropTypes.func,
  requesting: PropTypes.bool,
};

OneLinerAttemptsCard.defaultProps = {
  attempts: [],
  defaultOneLinerId: null,
  onRegenerate: () => {},
  requesting: false,
};

export default OneLinerAttemptsCard;
