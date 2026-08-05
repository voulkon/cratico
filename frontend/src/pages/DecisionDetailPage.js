import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import apiClient from '../api/client';
import { getAIModels } from '../api/aiApi';
import ModelDropdown from '../components/ModelDropdown';
import AnnotatedText from '../components/AnnotatedText';
import TopBarSlot from '../components/TopBarSlot';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import './DecisionDetailPage.css';
import '../components/StatCard.css';
import EntityDisplay from '../components/EntityDisplay';
import { formatAmount, formatDate } from '../utils/dateUtils';
import { useDecisionAI } from '../hooks/useDecisionAI';
import { useTextProcesses } from '../hooks/useTextProcesses';
import CollapsibleCard from '../components/CollapsibleCard';
import {
  FinancialIcon,
  CalendarIcon,
  DocumentTypeIcon,
  OrganizationIcon,
  ChartIcon,
  UsersIcon,
  UserIcon,
  LinkIcon,
  FileIcon,
  BookOpenIcon,
  GlobeIcon,
  PaperclipIcon,
  SearchIcon,
  EyeIcon,
  DownloadIcon,
  SparklesIcon,
  InfoIcon,
  LoaderIcon,
  AlertIcon
} from '../components/Icons';

const DecisionDetailPage = () => {
  const { ada: id } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [decision, setDecision] = useState(null);
  useDocumentTitle(decision?.subject || `Decision ${id}`);
  const [entityRelationships, setEntityRelationships] = useState([]);
  const [relatedDecisions, setRelatedDecisions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // ── Document content (inline) ──────────────────────────────────────
  const [docContent, setDocContent] = useState(null);       // raw_text when COMPLETED
  const [docStatus, setDocStatus] = useState(null);          // PENDING | PROCESSING | COMPLETED | FAILED | NOT_FOUND
  const [docMeta, setDocMeta] = useState(null);              // { character_count, page_count, extraction_provider, ... }
  const [docLoading, setDocLoading] = useState(false);       // fetching content
  const [docRequesting, setDocRequesting] = useState(false); // requesting extraction
  const pollRef = useRef(null);
  const aiPollRef = useRef(null);

  const fetchDocumentContent = useCallback(async () => {
    try {
      setDocLoading(true);
      const response = await apiClient.get(`/decisions/${id}/content/?include=spans`);
      const data = response.data;
      setDocStatus(data.status);
      if (data.status === 'COMPLETED' && data.raw_text) {
        setDocContent(data.raw_text);
        setDocMeta({
          character_count: data.character_count,
          page_count: data.page_count,
          extraction_provider: data.extraction_provider,
          extraction_date: data.extraction_date,
          processing_time_ms: data.processing_time_ms,
        });
        // Capture text-process runs + resolution (for annotated view)
        setProcessRuns(data.runs || []);
        setProcessResolution(data.resolution || null);
      } else {
        setDocContent(null);
        setDocMeta(null);
        setProcessRuns([]);
        setProcessResolution(null);
      }
    } catch (err) {
      console.error('Error fetching document content:', err);
      setDocStatus('ERROR');
      setDocContent(null);
    } finally {
      setDocLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Initial fetch + polling while extraction is in flight
  useEffect(() => {
    fetchDocumentContent();

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchDocumentContent]);

  useEffect(() => {
    if (docStatus === 'PENDING' || docStatus === 'PROCESSING') {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(fetchDocumentContent, 4000);
    } else {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [docStatus, fetchDocumentContent]);

  const fetchDecisionData = useCallback(async () => {
    try {
      setLoading(true);

      const decisionResponse = await apiClient.get(`/decisions/${id}/`);
      setDecision(decisionResponse.data);

      const entitiesResponse = await apiClient.get(`/decisions/${id}/entities/`);
      setEntityRelationships(entitiesResponse.data.relationships);

      const relatedResponse = await apiClient.get(`/decisions/${id}/related/`);
      setRelatedDecisions(relatedResponse.data.results);

    } catch (err) {
      console.error('Error fetching decision data:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchDecisionData();
  }, [fetchDecisionData]);

  const { aiAnalyses, requestExtraction, requestAISummary } = useDecisionAI(decision, fetchDecisionData);

  const {
    viewMode, setViewMode,
    processRuns, setProcessRuns,
    setProcessResolution,
    processList, selectedProcess, setSelectedProcess,
    processRunning, handleRunProcess,
  } = useTextProcesses(id, fetchDocumentContent);

  // Model selection for AI summarization
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [aiRequesting, setAiRequesting] = useState(false);
  // Track which AI summaries are expanded
  const [expandedSummaries, setExpandedSummaries] = useState({});

  const toggleSummary = (key) => {
    setExpandedSummaries(prev => ({ ...prev, [key]: !prev[key] }));
  };

  // Fetch available models for the dropdown
  useEffect(() => {
    getAIModels().then(data => {
      if (data?.models) setModels(data.models);
    }).catch(() => {});
  }, []);

  // AI summary polling while any analysis is RUNNING
  useEffect(() => {
    const hasRunning = aiAnalyses.some(a => a.status === 'RUNNING');
    if (hasRunning) {
      if (aiPollRef.current) clearInterval(aiPollRef.current);
      aiPollRef.current = setInterval(fetchDecisionData, 4000);
    } else {
      if (aiPollRef.current) {
        clearInterval(aiPollRef.current);
        aiPollRef.current = null;
      }
    }
    return () => {
      if (aiPollRef.current) clearInterval(aiPollRef.current);
    };
  }, [aiAnalyses, fetchDecisionData]);

  const handleRequestContent = async () => {
    try {
      setDocRequesting(true);
      await requestExtraction();
      // Immediately poll — the backend just queued the task
      setDocStatus('PENDING');
    } catch (err) {
      alert(typeof err === 'string' ? err : t('decisionDetail.extractionFailed'));
    } finally {
      setDocRequesting(false);
    }
  };

  const handleRequestAISummary = async (model = null) => {
    try {
      setAiRequesting(true);
      await requestAISummary(false, model);
      // Refresh immediately to show the new RUNNING analysis
      fetchDecisionData();
    } catch (err) {
      alert(typeof err === 'string' ? err : t('decisionDetail.aiSummaryFailed'));
    } finally {
      setAiRequesting(false);
    }
  };

  if (loading) {
    return (
      <>
        <TopBarSlot>
          <div className="entity-header-topbar">
            <span className="entity-title-topbar">{t('decisionDetail.loadingDecision')}</span>
            <span className="entity-subtitle-topbar">ADA: {id}</span>
          </div>
        </TopBarSlot>
        <div className="loading-container">
          <h2>{t('decisionDetail.loadingDecision')}</h2>
          <div className="spinner"></div>
        </div>
      </>
    );
  }

  if (error) {
    return (
      <div className="error-container">
        <h2>{t('decisionDetail.errorLoadingDecision')}</h2>
        <p>{error}</p>
        <button onClick={() => navigate(-1)} className="back-button">
          {t('common.goBack')}
        </button>
      </div>
    );
  }

  if (!decision) {
    return (
      <div className="not-found-container">
        <h2>{t('decisionDetail.decisionNotFound')}</h2>
        <p>{t('decisionDetail.decisionNotFoundMessage', { id })}</p>
        <button onClick={() => navigate(-1)} className="back-button">
          {t('common.goBack')}
        </button>
      </div>
    );
  }

  return (
    <div className="decision-detail-page">
      {/* Top-bar decision header (rendered via TopBarSlot portal) —
          always keeps the current decision visible in the fixed top bar */}
      <TopBarSlot>
        <div className="entity-header-topbar">
          <span className="entity-title-topbar">{decision.subject}</span>
          <span className="entity-subtitle-topbar">
            {t('decisionDetail.decisionLabel')} {decision.ada}
            {decision.status && <span> · {decision.status}</span>}
          </span>
        </div>
      </TopBarSlot>

      {/* Header Section — centered */}
      <div className="decision-header">
        <div className="breadcrumb">
          <button onClick={() => navigate(-1)} className="breadcrumb-link">
            {t('navigation.back')}
          </button>
          <span className="breadcrumb-separator">•</span>
          <span>{t('decisionDetail.decisionDetails')}</span>
        </div>

        <div className="decision-title-row">
          <h1 className="decision-title">{decision.subject}</h1>

          {/* All metadata lives behind a single uniform (i) hover card */}
          <span className="metadata-info" tabIndex={0}>
            <InfoIcon size={16} />
            <div className="metadata-popover">
              {decision.ada && (
                <div className="metadata-row">
                  <span className="metadata-key">ADA</span>
                  <span className="metadata-value">{decision.ada}</span>
                </div>
              )}
              <div className="metadata-row">
                <span className="metadata-key">{t('decisionDetail.versionId')}</span>
                <span className="metadata-value">{decision.version_id || '—'}</span>
              </div>
              <div className="metadata-row">
                <span className="metadata-key">{t('decisionDetail.statusLabel')}</span>
                <span className="metadata-value">{decision.status}</span>
              </div>
              {decision.protocol_number && (
                <div className="metadata-row">
                  <span className="metadata-key">{t('decisionDetail.protocol')}</span>
                  <span className="metadata-value">{decision.protocol_number}</span>
                </div>
              )}
            </div>
          </span>
        </div>
      </div>

      {/* AI Analyses card is rendered below the document content card */}
      {false && (
      <CollapsibleCard
        title={
          <span className="ai-analysis-title">
            <SparklesIcon size={16} /> {t('decisionDetail.aiAnalysis')}
            {aiAnalyses.filter(a => a.status === 'COMPLETED').length > 0 && (
              <span className="ai-analysis-count">
                {' '}({aiAnalyses.filter(a => a.status === 'COMPLETED').length})
              </span>
            )}
          </span>
        }
        subtitle={
          aiAnalyses.some(a => a.status === 'RUNNING') ? (
            <span className="ai-analysis-subtitle">{t('decisionDetail.aiSummaryRunning')}</span>
          ) : null
        }
        badge={
          aiAnalyses.some(a => a.status === 'RUNNING') ? (
            <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
          ) : null
        }
        defaultOpen={aiAnalyses.filter(a => a.status === 'COMPLETED').length > 0}
        className="ai-analysis-collapsible"
      >
        {/* Model picker + single summarize button — always visible */}
        <div className="ai-analysis-request-row">
          <div className="ai-model-picker-row">
            <ModelDropdown
              models={models}
              value={selectedModel}
              onChange={setSelectedModel}
              placeholder={t('aiSettings.usePipelineDefault')}
              t={t}
            />
          </div>
          <button
            className="document-link ai-summary-retry"
            onClick={() => handleRequestAISummary(selectedModel || null)}
            disabled={aiRequesting}
          >
            {aiRequesting ? <LoaderIcon className="spinner" size={14} /> : <SparklesIcon size={14} />}
            {' '}{t('decisionDetail.requestAISummary')}
          </button>
        </div>

        {/* Running analyses */}
        {aiAnalyses.filter(a => a.status === 'RUNNING').map((a, i) => (
          <div key={`running-${i}`} className="ai-summary-item ai-summary-item--running">
            <div className="ai-summary-item-header">
              <span className="ai-model-badge">{a.model_used || t('decisionCard.defaultModel')}</span>
              <div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
            </div>
            <p className="ai-summary-item-status">{t('decisionDetail.aiSummaryRunning')}</p>
          </div>
        ))}

        {/* Completed analyses — click header to expand/collapse */}
        {aiAnalyses.filter(a => a.status === 'COMPLETED').map((a, i) => {
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
        {aiAnalyses.filter(a => a.status === 'FAILED').map((a, i) => (
          <div key={`failed-${i}`} className="ai-summary-item ai-summary-item--failed">
            <div className="ai-summary-item-header">
              <span className="ai-model-badge">{a.model_used || t('decisionCard.defaultModel')}</span>
              <AlertIcon size={14} />
            </div>
            <p className="ai-summary-item-error">{a.error_message || t('decisionDetail.aiSummaryFailed')}</p>
          </div>
        ))}

        {/* No summaries yet */}
        {aiAnalyses.length === 0 && (
          <div className="ai-summary-placeholder">
            <SparklesIcon size={28} />
            <p>{t('decisionDetail.aiAnalysisDescription')}</p>
          </div>
        )}
      </CollapsibleCard>
      )}

      {/* Hero amount */}
      {decision.amount != null && (
        <div className="amount-hero">
          <div className="amount-hero-value">{formatAmount(decision.amount)}</div>
          <div className="amount-hero-meta">
            {decision.currency && decision.currency !== 'EUR' && (
              <span>{decision.currency}</span>
            )}
            {decision.financial_year && (
              <span>{t('decisionDetail.financialYear')} {decision.financial_year}</span>
            )}
          </div>
        </div>
      )}

      {/* Core Information — compact inline strip (amount is already
          shown in the hero, so the financial card was redundant) */}
      <div className="decision-facts">
        <span className="fact-item">
          <CalendarIcon size={14} />
          <span className="fact-label">{t('decisionDetail.timeline')}</span>
          <strong>{formatDate(decision.issue_date)}</strong>
        </span>
        {decision.publish_timestamp && (
          <span className="fact-item">
            <span className="fact-label">{t('decisionDetail.published')}</span>
            <strong>{formatDate(decision.publish_timestamp)}</strong>
          </span>
        )}
        {decision.submission_timestamp && (
          <span className="fact-item">
            <span className="fact-label">{t('decisionDetail.submitted')}</span>
            <strong>{formatDate(decision.submission_timestamp)}</strong>
          </span>
        )}
        <span className="fact-item">
          <DocumentTypeIcon size={14} />
          <span className="fact-label">{t('decisionDetail.decisionType')}</span>
          <strong>
            {decision.decision_type
              ? decision.decision_type.label
              : t('decisionDetail.typeNotSpecified')}
          </strong>
        </span>
        {decision.financial_year && (
          <span className="fact-item">
            <FinancialIcon size={14} />
            <span className="fact-label">{t('decisionDetail.financialYear')}</span>
            <strong>{decision.financial_year}</strong>
          </span>
        )}
      </div>

      {/* ── Document Content (collapsible, with polling) ──────────────── */}
      <CollapsibleCard
        title={
          <span className="doc-content-title">
            <BookOpenIcon size={16} /> {t('decisionDetail.documentContent')}
          </span>
        }
        subtitle={
          docStatus === 'COMPLETED' && docMeta ? (
            <span className="doc-content-subtitle">
              {t('decisionDetail.documentContentMeta', {
                chars: docMeta.character_count?.toLocaleString() || '?',
                pages: docMeta.page_count ?? '?',
                provider: docMeta.extraction_provider || '?',
              })}
              {docMeta.processing_time_ms && ` · ${docMeta.processing_time_ms}ms`}
            </span>
          ) : null
        }
        badge={
          docStatus === 'COMPLETED' ? (
            <span className="doc-content-badge">✓</span>
          ) : docStatus === 'PENDING' || docStatus === 'PROCESSING' ? (
            <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
          ) : docStatus === 'FAILED' ? (
            <AlertIcon size={14} />
          ) : null
        }
        defaultOpen={docStatus === 'COMPLETED'}
        className="document-content-collapsible"
      >
        {docLoading && !docContent && docStatus !== 'COMPLETED' ? (
          <div className="document-content-placeholder">
            <div className="spinner" />
            <p>{t('common.loading')}</p>
          </div>
        ) : docStatus === 'COMPLETED' && docContent ? (
          <>
            {/* View toggle */}
            <div className="view-toggle">
              <button
                className={viewMode === 'rendered' ? 'active' : ''}
                onClick={() => setViewMode('rendered')}
              >
                Rendered
              </button>
              <button
                className={viewMode === 'annotated' ? 'active' : ''}
                onClick={() => setViewMode('annotated')}
              >
                Annotated
              </button>
            </div>

            {/* Process controls — only shown in annotated mode */}
            {viewMode === 'annotated' && (
              <div className="process-controls">
                <select
                  value={selectedProcess}
                  onChange={e => setSelectedProcess(e.target.value)}
                  style={{ fontSize: 12, padding: '3px 6px', borderRadius: 4, border: '1px solid var(--border-color, #444)', background: 'var(--surface, #1e1e1e)', color: 'var(--text-primary, #e0e0e0)' }}
                >
                  <option value="">-- Run a process --</option>
                  {processList.map(p => (
                    <option key={p.slug} value={p.slug}>{p.name}</option>
                  ))}
                </select>
                <button
                  className="process-trigger-btn process-trigger-btn--primary"
                  disabled={!selectedProcess || processRunning}
                  onClick={() => handleRunProcess()}
                >
                  {processRunning ? <LoaderIcon className="spinner" size={12} /> : <SparklesIcon size={12} />}
                  {' '}Run
                </button>
                {/* Quick-run buttons for common processes */}
                {processList.filter(p => !processRuns.some(r => r.process === p.slug && r.status === 'COMPLETED')).slice(0, 2).map(p => (
                  <button
                    key={p.slug}
                    className="process-trigger-btn"
                    disabled={processRunning}
                    onClick={() => handleRunProcess(p.slug)}
                  >
                    Detect {p.name}
                  </button>
                ))}
              </div>
            )}

            {/* Content: annotated or rendered */}
            {viewMode === 'annotated' ? (
              <AnnotatedText
                rawText={docContent}
                runs={processRuns}
              />
            ) : (
              <div className="document-content-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {docContent}
                </ReactMarkdown>
              </div>
            )}
          </>
        ) : docStatus === 'PENDING' || docStatus === 'PROCESSING' ? (
          <div className="document-content-placeholder">
            <div className="spinner" />
            <p>{t('decisionDetail.documentContentExtractionInProgress')}</p>
          </div>
        ) : docStatus === 'FAILED' ? (
          <div className="document-content-placeholder">
            <AlertIcon size={28} />
            <p>{t('decisionDetail.documentContentExtractionFailed', { error: '' })}</p>
            <button
              className="document-link document-content-retry"
              onClick={handleRequestContent}
              disabled={docRequesting}
            >
              {docRequesting ? <LoaderIcon className="spinner" size={14} /> : <BookOpenIcon size={14} />}
              {' '}{t('decisionDetail.documentContentRequestExtraction')}
            </button>
          </div>
        ) : docStatus === 'NOT_FOUND' ? (
          <div className="document-content-placeholder">
            <BookOpenIcon size={28} />
            <p>{t('decisionDetail.documentContentNotRequested')}</p>
            <button
              className="document-link document-content-retry"
              onClick={handleRequestContent}
              disabled={docRequesting}
            >
              {docRequesting ? <LoaderIcon className="spinner" size={14} /> : <BookOpenIcon size={14} />}
              {' '}{t('decisionDetail.documentContentRequestExtraction')}
            </button>
          </div>
        ) : (
          <div className="document-content-placeholder">
            <p>{t('decisionDetail.documentContentNotAvailable')}</p>
            <button
              className="document-link document-content-retry"
              onClick={handleRequestContent}
              disabled={docRequesting}
            >
              {docRequesting ? <LoaderIcon className="spinner" size={14} /> : <BookOpenIcon size={14} />}
              {' '}{t('decisionDetail.documentContentRequestExtraction')}
            </button>
          </div>
        )}
      </CollapsibleCard>

      {/* ── AI Analyses (multi-model, collapsible, with polling) —
          rendered directly below the document content so the summary
          follows the raw text ──── */}
      <CollapsibleCard
        title={
          <span className="ai-analysis-title">
            <SparklesIcon size={16} /> {t('decisionDetail.aiAnalysis')}
            {aiAnalyses.filter(a => a.status === 'COMPLETED').length > 0 && (
              <span className="ai-analysis-count">
                {' '}({aiAnalyses.filter(a => a.status === 'COMPLETED').length})
              </span>
            )}
          </span>
        }
        subtitle={
          aiAnalyses.some(a => a.status === 'RUNNING') ? (
            <span className="ai-analysis-subtitle">{t('decisionDetail.aiSummaryRunning')}</span>
          ) : null
        }
        badge={
          aiAnalyses.some(a => a.status === 'RUNNING') ? (
            <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
          ) : null
        }
        defaultOpen={aiAnalyses.filter(a => a.status === 'COMPLETED').length > 0}
        className="ai-analysis-collapsible"
      >
        {/* Model picker + single summarize button — always visible */}
        <div className="ai-analysis-request-row">
          <div className="ai-model-picker-row">
            <ModelDropdown
              models={models}
              value={selectedModel}
              onChange={setSelectedModel}
              placeholder={t('aiSettings.usePipelineDefault')}
              t={t}
            />
          </div>
          <button
            className="document-link ai-summary-retry"
            onClick={() => handleRequestAISummary(selectedModel || null)}
            disabled={aiRequesting}
          >
            {aiRequesting ? <LoaderIcon className="spinner" size={14} /> : <SparklesIcon size={14} />}
            {' '}{t('decisionDetail.requestAISummary')}
          </button>
        </div>

        {/* Running analyses */}
        {aiAnalyses.filter(a => a.status === 'RUNNING').map((a, i) => (
          <div key={`running-${i}`} className="ai-summary-item ai-summary-item--running">
            <div className="ai-summary-item-header">
              <span className="ai-model-badge">{a.model_used || t('decisionCard.defaultModel')}</span>
              <div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
            </div>
            <p className="ai-summary-item-status">{t('decisionDetail.aiSummaryRunning')}</p>
          </div>
        ))}

        {/* Completed analyses — click header to expand/collapse */}
        {aiAnalyses.filter(a => a.status === 'COMPLETED').map((a, i) => {
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
        {aiAnalyses.filter(a => a.status === 'FAILED').map((a, i) => (
          <div key={`failed-${i}`} className="ai-summary-item ai-summary-item--failed">
            <div className="ai-summary-item-header">
              <span className="ai-model-badge">{a.model_used || t('decisionCard.defaultModel')}</span>
              <AlertIcon size={14} />
            </div>
            <p className="ai-summary-item-error">{a.error_message || t('decisionDetail.aiSummaryFailed')}</p>
          </div>
        ))}

        {/* No summaries yet */}
        {aiAnalyses.length === 0 && (
          <div className="ai-summary-placeholder">
            <SparklesIcon size={28} />
            <p>{t('decisionDetail.aiAnalysisDescription')}</p>
          </div>
        )}
      </CollapsibleCard>

      {/* Organizational Context — stat cards (Organization / Signers / Units) */}
      <div className="section-block">
        <h3 className="section-heading">
          <OrganizationIcon size={20} /> {t('decisionDetail.organizationalContext')}
        </h3>
        <div className="statistics-grid decision-org-grid">
          {decision.organization && (
            <div className="stat-card">
              <h3 className="stat-title">
                <OrganizationIcon size={16} /> {t('decisionDetail.organizationLabel')}
              </h3>
              <div className="org-card-values">
                <button
                  className="org-card-link"
                  onClick={() => navigate(`/entity/organization/${decision.organization.uid}`)}
                  title={t('decisionDetail.viewOrganizationDetails')}
                >
                  {decision.organization.label}
                </button>
              </div>
              <button
                className="org-chart-link"
                onClick={() => navigate(`/organizations?uid=${decision.organization.uid}`)}
                title={t('decisionDetail.viewOrganizationChart')}
              >
                <ChartIcon size={14} /> {t('decisionDetail.viewOrgChart')}
              </button>
            </div>
          )}

          {decision.signers && decision.signers.length > 0 && (
            <div className="stat-card">
              <h3 className="stat-title">
                <UsersIcon size={16} /> {t('decisionDetail.signersLabel')}
              </h3>
              <div className="org-card-values">
                {decision.signers.map(signer => (
                  <button
                    key={signer.uid}
                    className="org-card-link"
                    onClick={() => navigate(`/entity/signer/${signer.uid}`)}
                    title={t('decisionDetail.viewSignerDetails')}
                  >
                    <UserIcon size={14} /> {signer.first_name} {signer.last_name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {decision.units && decision.units.length > 0 && (
            <div className="stat-card">
              <h3 className="stat-title">
                <OrganizationIcon size={16} /> {t('decisionDetail.unitsLabel')}
              </h3>
              <div className="org-card-values">
                {decision.units.map(unit => (
                  <button
                    key={unit.uid}
                    className="org-card-link"
                    onClick={() => navigate(`/entity/unit/${unit.uid}`)}
                    title={t('decisionDetail.viewUnitDetails')}
                  >
                    {unit.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Entity Relationships */}
      {entityRelationships && entityRelationships.length > 0 && (
        <div className="section-block entities-section">
          <h3 className="section-heading">
            <LinkIcon size={20} /> {t('decisionDetail.relatedEntities')}
          </h3>
          <p className="section-description">
            {t('decisionDetail.relatedEntitiesDescription')}
          </p>
          <EntityDisplay
            entityRelationships={entityRelationships}
            showRoleBadge={false}
            compact={false}
            showCompanies={false}
          />
        </div>
      )}

      {/* Documents — uniform action pills */}
      <div className="section-block document-section">
        <h3 className="section-heading">
          <FileIcon size={20} /> {t('decisionDetail.documents')}
        </h3>

        <div className="document-actions">
          {decision.diavgeia_doc_url && (
            <button
              className="document-link"
              onClick={() => window.open(decision.diavgeia_doc_url, '_blank')}
              title={t('decisionDetail.viewOriginalDocumentTooltip')}
            >
              <EyeIcon size={15} /> {t('decisionDetail.viewDocument')}
            </button>
          )}

          {decision.document_url && (
            <button
              className="document-link"
              onClick={() => window.open(decision.document_url, '_blank')}
              title={t('decisionDetail.downloadDocumentTooltip')}
            >
              <DownloadIcon size={15} /> {t('decisionDetail.downloadDocument')}
            </button>
          )}

          {decision.diavgeia_page_url && (
            <button
              className="document-link"
              onClick={() => window.open(decision.diavgeia_page_url, '_blank')}
              title={t('decisionDetail.viewOnDiavgeiaTooltip')}
            >
              <GlobeIcon size={15} /> {t('decisionDetail.viewOnDiavgeia')}
            </button>
          )}
        </div>

        {decision.attachments && decision.attachments.length > 0 && (
          <div className="attachments-list">
            <h4><PaperclipIcon size={16} /> {t('decisionDetail.attachments', { count: decision.attachments.length })}</h4>
            {decision.attachments.map((attachment, index) => {
              const attachmentUrl = decision.ada && attachment.attachment_id
                ? `https://diavgeia.gov.gr/luminapi/api/decisions/${decision.ada}/attachments/${attachment.attachment_id}/document`
                : null;
              return (
                <div key={index} className="attachment-item">
                  <span className="attachment-icon"><PaperclipIcon size={14} /></span>
                  {attachmentUrl ? (
                    <a
                      className="attachment-name attachment-link"
                      href={attachmentUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={t('decisionDetail.downloadAttachmentTooltip', { filename: attachment.filename })}
                    >
                      {attachment.filename}
                    </a>
                  ) : (
                    <span className="attachment-name">{attachment.filename}</span>
                  )}
                  {attachment.description && (
                    <span className="attachment-description">{attachment.description}</span>
                  )}
                  <span className="attachment-type">({attachment.mime_type})</span>
                </div>
              );
            })}
          </div>
        )}

        {(decision.document_checksum || (decision.attachments || []).some(a => a.checksum)) && (
          <details className="document-debug-details">
            <summary>{t('decisionDetail.technicalDetails')}</summary>
            <div className="document-debug-body">
              {decision.document_checksum && (
                <p><strong>{t('decisionDetail.documentChecksum')}:</strong> <code>{decision.document_checksum}</code></p>
              )}
              {(decision.attachments || []).filter(a => a.checksum).map((a, i) => (
                <p key={i}>
                  <strong>{a.filename}:</strong> <code>{a.checksum}</code>
                </p>
              ))}
            </div>
          </details>
        )}
      </div>

      {/* Related Decisions */}
      {relatedDecisions && relatedDecisions.length > 0 && (
        <div className="section-block related-decisions">
          <h3 className="section-heading">
            <SearchIcon size={20} /> {t('decisionDetail.relatedDecisions')}
          </h3>
          <p className="section-description">
            {t('decisionDetail.relatedDecisionsDescription')}
          </p>
          <div className="related-grid">
            {relatedDecisions.slice(0, 6).map(related => (
              <button
                key={related.id}
                className="clickable-entity related-decision"
                onClick={() => navigate(`/decision/${related.id}`)}
                title={t('decisionDetail.viewRelatedDecision')}
              >
                <div className="related-header">
                  <span className="related-ada">{related.ada}</span>
                  {related.amount != null && (
                    <span className="related-amount">
                      {formatAmount(related.amount)}
                    </span>
                  )}
                </div>
                <div className="related-subject">
                  {related.subject.length > 120
                    ? related.subject.substring(0, 120) + '...'
                    : related.subject
                  }
                </div>
                <div className="related-meta">
                  {formatDate(related.issue_date)}
                  {related.decision_type && (
                    <span> • {related.decision_type.label}</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default DecisionDetailPage;
