import React, { useState } from 'react';
import PropTypes from 'prop-types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useTranslation } from '../contexts/TranslationContext';
import { formatDate } from '../utils/dateUtils';
import CollapsibleCard from './CollapsibleCard';
import ModelDropdown from './ModelDropdown';
import { AlertIcon, LoaderIcon, SparklesIcon } from './Icons';
import './DecisionAICards.css';

/**
 * AIAnalysesCard — multi-model AI summaries for a decision.
 *
 * Handles RUNNING / COMPLETED / FAILED analyses, per-model expansion, and
 * the model picker used to request a new summary.
 *
 * Props:
 *   analyses        – [{ id, status, model_used, summary, cost_usd,
 *                       completed_at, error_message }]
 *   models          – available models passed to ModelDropdown
 *   selectedModel   – currently selected model id ('' for pipeline default)
 *   onSelectModel   – (modelId) => void
 *   onRequestSummary– (modelId | null) => void
 *   requesting      – true while the request is in flight
 */
const AIAnalysesCard = ({
  analyses,
  models,
  selectedModel,
  onSelectModel,
  onRequestSummary,
  requesting,
}) => {
  const { t } = useTranslation();
  const [expandedSummaries, setExpandedSummaries] = useState({});

  const toggleSummary = (key) => {
    setExpandedSummaries((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const completed = analyses.filter((a) => a.status === 'COMPLETED');
  const running = analyses.filter((a) => a.status === 'RUNNING');
  const failed = analyses.filter((a) => a.status === 'FAILED');

  return (
    <CollapsibleCard
      title={
        <span className="ai-analysis-title">
          <SparklesIcon size={16} /> {t('decisionDetail.aiAnalysis')}
          {completed.length > 0 && (
            <span className="ai-analysis-count"> ({completed.length})</span>
          )}
        </span>
      }
      subtitle={
        running.length > 0 ? (
          <span className="ai-analysis-subtitle">{t('decisionDetail.aiSummaryRunning')}</span>
        ) : null
      }
      badge={
        running.length > 0 ? (
          <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
        ) : null
      }
      defaultOpen={completed.length > 0}
      className="ai-analysis-collapsible"
    >
      {/* Model picker + single summarize button — always visible */}
      <div className="ai-analysis-request-row">
        <div className="ai-model-picker-row">
          <ModelDropdown
            models={models}
            value={selectedModel}
            onChange={onSelectModel}
            placeholder={t('aiSettings.usePipelineDefault')}
            t={t}
          />
        </div>
        <button
          className="document-link ai-summary-retry"
          onClick={() => onRequestSummary(selectedModel || null)}
          disabled={requesting}
        >
          {requesting ? <LoaderIcon className="spinner" size={14} /> : <SparklesIcon size={14} />}
          {' '}{t('decisionDetail.requestAISummary')}
        </button>
      </div>

      {/* Running analyses */}
      {running.map((a, i) => (
        <div key={`running-${i}`} className="ai-summary-item ai-summary-item--running">
          <div className="ai-summary-item-header">
            <span className="ai-model-badge">{a.model_used || t('decisionCard.defaultModel')}</span>
            <div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
          </div>
          <p className="ai-summary-item-status">{t('decisionDetail.aiSummaryRunning')}</p>
        </div>
      ))}

      {/* Completed analyses — click header to expand/collapse */}
      {completed.map((a, i) => {
        const key = a.id || i;
        const expanded = expandedSummaries[key];
        return (
          <div key={key} className="ai-summary-item">
            <div
              className="ai-summary-item-header ai-summary-item-header--clickable"
              onClick={() => toggleSummary(key)}
              title={expanded ? t('decisionCard.collapse') : t('decisionCard.expand')}
            >
              <span className="ai-model-badge">{a.model_used || t('decisionCard.defaultModel')}</span>
              <span className="ai-summary-item-cost">
                {a.cost_usd && `$${a.cost_usd}`}
                {a.completed_at && ` · ${formatDate(a.completed_at)}`}
                <span className="ai-summary-chevron">{expanded ? '▴' : '▾'}</span>
              </span>
            </div>
            {expanded && (
              <div className="ai-summary-text">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {a.summary}
                </ReactMarkdown>
              </div>
            )}
          </div>
        );
      })}

      {/* Failed analyses — show error, no retry (pick model again from dropdown to retry) */}
      {failed.map((a, i) => (
        <div key={`failed-${i}`} className="ai-summary-item ai-summary-item--failed">
          <div className="ai-summary-item-header">
            <span className="ai-model-badge">{a.model_used || t('decisionCard.defaultModel')}</span>
            <AlertIcon size={14} />
          </div>
          <p className="ai-summary-item-error">{a.error_message || t('decisionDetail.aiSummaryFailed')}</p>
        </div>
      ))}

      {/* No summaries yet */}
      {analyses.length === 0 && (
        <div className="ai-summary-placeholder">
          <SparklesIcon size={28} />
          <p>{t('decisionDetail.aiAnalysisDescription')}</p>
        </div>
      )}
    </CollapsibleCard>
  );
};

AIAnalysesCard.propTypes = {
  analyses: PropTypes.arrayOf(PropTypes.shape({
    id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    status: PropTypes.string,
    model_used: PropTypes.string,
    summary: PropTypes.string,
    cost_usd: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    completed_at: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    error_message: PropTypes.string,
  })),
  models: PropTypes.array,
  selectedModel: PropTypes.string,
  onSelectModel: PropTypes.func,
  onRequestSummary: PropTypes.func,
  requesting: PropTypes.bool,
};

AIAnalysesCard.defaultProps = {
  analyses: [],
  models: [],
  selectedModel: '',
  onSelectModel: () => {},
  onRequestSummary: () => {},
  requesting: false,
};

export default AIAnalysesCard;
