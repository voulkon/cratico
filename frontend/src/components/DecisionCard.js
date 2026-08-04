import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useTranslation } from '../contexts/TranslationContext';
import apiClient from '../api/client';
import CollapsibleCard from './CollapsibleCard';
import './DecisionCard.css';

import {OrganizationIcon, PenIcon, CalendarIcon, EyeIcon, DownloadIcon, ExternalLinkIcon, BookOpenIcon, LoaderIcon, ChevronDown, ChevronUp, SparklesIcon, SearchIcon, AlertIcon} from './Icons.js';

import EntityDisplay from './EntityDisplay';
import { getMainRecipient, getTotalAmount, groupEntityRelationships, getCounterpartEntities } from '../utils/decisionUtils';
import { formatDate } from '../utils/dateUtils';



const DecisionCard = ({ decision, formatAmount, index, isLastItem, onViewDocumentContent }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // ── Document content (self-contained) ──────────────────────────────
  const [docContent, setDocContent] = useState(null);
  const [docStatus, setDocStatus] = useState(null);
  const [docMeta, setDocMeta] = useState(null);
  const [docLoading, setDocLoading] = useState(false);
  const docPollRef = useRef(null);

  // ── AI summary (self-contained) ────────────────────────────────────
  const [aiSummary, setAiSummary] = useState(null);
  const [aiStatus, setAiStatus] = useState(null);
  const [aiMeta, setAiMeta] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiRequesting, setAiRequesting] = useState(false);
  const aiPollRef = useRef(null);

  const [entityRelationships, setEntityRelationships] = useState(null);
  const [showEntities, setShowEntities] = useState(false);
  const [loadingEntities, setLoadingEntities] = useState(false);
  const [showKae, setShowKae] = useState(false);

  // ── Fetch document content ─────────────────────────────────────────
  const fetchDocumentContent = useCallback(async () => {
    try {
      setDocLoading(true);
      const response = await apiClient.get(`/decisions/${decision.id}/content/`);
      const data = response.data;
      setDocStatus(data.status);
      if (data.status === 'COMPLETED' && data.raw_text) {
        setDocContent(data.raw_text);
        setDocMeta({
          character_count: data.character_count,
          page_count: data.page_count,
          extraction_provider: data.extraction_provider,
          processing_time_ms: data.processing_time_ms,
        });
      } else {
        setDocContent(null);
        setDocMeta(null);
      }
    } catch {
      setDocStatus('ERROR');
    } finally {
      setDocLoading(false);
    }
  }, [decision.id]);

  // ── Fetch AI summary ───────────────────────────────────────────────
  const fetchAISummary = useCallback(async () => {
    try {
      setAiLoading(true);
      const response = await apiClient.get(`/decisions/${decision.id}/`);
      const ai = response.data?.ai_analysis;
      if (ai) {
        setAiStatus(ai.status);
        if (ai.status === 'COMPLETED' && ai.summary) {
          setAiSummary(ai.summary);
          setAiMeta({
            model_used: ai.model_used,
            cost_usd: ai.cost_usd,
            completed_at: ai.completed_at,
          });
        }
      } else {
        setAiStatus('NOT_FOUND');
      }
    } catch {
      setAiStatus('ERROR');
    } finally {
      setAiLoading(false);
    }
  }, [decision.id]);

  // Initial fetch on mount
  useEffect(() => {
    if (decision.has_document_content) fetchDocumentContent();
    fetchAISummary();
  }, [decision.has_document_content, fetchDocumentContent, fetchAISummary]);

  // Polling for document extraction
  useEffect(() => {
    if (docStatus === 'PENDING' || docStatus === 'PROCESSING') {
      docPollRef.current = setInterval(fetchDocumentContent, 4000);
    } else {
      if (docPollRef.current) { clearInterval(docPollRef.current); docPollRef.current = null; }
    }
    return () => { if (docPollRef.current) clearInterval(docPollRef.current); };
  }, [docStatus, fetchDocumentContent]);

  // Polling for AI summary
  useEffect(() => {
    if (aiStatus === 'RUNNING') {
      aiPollRef.current = setInterval(fetchAISummary, 4000);
    } else {
      if (aiPollRef.current) { clearInterval(aiPollRef.current); aiPollRef.current = null; }
    }
    return () => { if (aiPollRef.current) clearInterval(aiPollRef.current); };
  }, [aiStatus, fetchAISummary]);

  // Check if entity data is already included in decision (from optimized endpoint)
  const hasPreloadedEntityData = decision.entity_amount !== undefined
    || decision.main_recipient !== undefined
    || decision.entities !== undefined;

  // ── Request AI summary ─────────────────────────────────────────────
  const handleRequestAISummary = async () => {
    try {
      setAiRequesting(true);
      await apiClient.post(`/ai/decisions/${decision.id}/summarize/`, {});
      setAiStatus('RUNNING');
    } catch {
      // silently fail — polling will pick up any status change
    } finally {
      setAiRequesting(false);
    }
  };

  // ── Request extraction (reuse parent callback or direct call) ──────
  const handleRequestContent = async () => {
    try {
      await apiClient.post(`/ai/decisions/${decision.id}/extract/`);
      setDocStatus('PENDING');
    } catch {
      // silently fail
    }
  };

  const handleViewEntities = async () => {
    if (entityRelationships) {
      setShowEntities(!showEntities);
      return;
    }

    setLoadingEntities(true);
    try {
      const response = await apiClient.get(`/decisions/${decision.id}/entities/`);

      // Group relationships by role and entity AFM
      const groupedRelationships = groupEntityRelationships(response.data.relationships);

      const processedData = {
        ...response.data,
        relationships: groupedRelationships
      };

      setEntityRelationships(processedData);
      setShowEntities(true);
    } catch (error) {
      console.error('Failed to fetch entity relationships:', error);
    } finally {
      setLoadingEntities(false);
    }
  };

  const handleOrganizationClick = (organizationUid) => {
    navigate(`/entity/organization/${organizationUid}`);
  };

  const handleSignerClick = (signerUid) => {
    navigate(`/entity/signer/${signerUid}`);
  };

  const handleEntityClick = (afm) => {
    navigate(`/entity/afm/${afm}`);
  };

  const handleCompanyClick = (company) => {
    // Navigate to the AFM entity page for this company
    navigate(`/entity/afm/${company.afm}`);
  };

  // NEW: Handle ADA click to navigate to decision detail page
  const handleAdaClick = () => {
    navigate(`/decision/${decision.id}`);
  };

  // Populate entity relationships from preloaded data (avoids N+1 API calls)
  useEffect(() => {
    if (decision.entities && !entityRelationships) {
      setEntityRelationships({ relationships: decision.entities });
    }
  }, [decision.entities, entityRelationships]);

  // NOTE: The auto-fetch useEffect was intentionally removed.
  // Entity data is now embedded in the decision list response by the backend
  // (via serialize_decision_with_entities + batch prefetch).  If a backend
  // endpoint still omits entities, the card gracefully degrades to showing
  // only the decision-level amount and the user can click "View Entities"
  // to fetch on demand.

  // Use utility functions to calculate recipient and amount
  const mainRecipient = getMainRecipient(decision, entityRelationships, hasPreloadedEntityData);
  const displayAmount = getTotalAmount(decision, entityRelationships, hasPreloadedEntityData, mainRecipient);
  const counterpartEntities = getCounterpartEntities(decision);

  return (
    <div className={`decision-card ${isLastItem ? 'last-item' : ''}`}>

      {/* Clickable Title */}
      <button
        className="decision-subject clickable-title"
        onClick={handleAdaClick}
        title={t('decisionCard.viewDecisionDetails')}
      >
        {decision.subject}
      </button>

      {/* Date and Decision Type Display */}
      <div className="decision-header-info">
        <div className="decision-date-prominent" title={t('decisionCard.issueDate')}>
          <CalendarIcon size={14} />
          <span className="date-value">
            {formatDate(decision.issue_date)}
          </span>
        </div>

        {decision.decision_type && (
          <div className="decision-type-badge" title={t('decisionCard.decisionType')}>
            {decision.decision_type.label}
          </div>
        )}
      </div>

      {/* Organization — above the amount */}
      {decision.organization && (
        <div className="decision-org-above" title={t('decisionCard.organization')}>
          <OrganizationIcon size={14} />
          <button
            className="metadata-value clickable"
            onClick={(e) => {
              e.stopPropagation();
              handleOrganizationClick(decision.organization.uid);
            }}
          >
            {decision.organization.label}
          </button>
        </div>
      )}

      {/* Simple amount and recipient display */}
      <div className="decision-main-info">
        {loadingEntities ? (
          <div className="loading-state"><LoaderIcon className="spinner" size={14} /> {t('common.loading')}</div>
        ) : (
          <>
            <div className="info-content">
              <div className="amount-display">
                {formatAmount(displayAmount)}
              </div>
              {mainRecipient && (
                <div className="recipient-display">
                  <span className="recipient-arrow">→</span>
                  <button
                    className="recipient-name"
                    onClick={() => handleEntityClick(mainRecipient.entity.afm)}
                    title={t('decisionCard.viewEntityDetails')}
                  >
                    {mainRecipient.entity.name}
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Signers — below the recipient */}
      {decision.signers && decision.signers.length > 0 && (
        <div className="decision-signers-below" title={decision.signers.length > 1 ? t('decisionCard.signers') : t('decisionCard.signer')}>
          <PenIcon size={14} />
          {decision.signers.map((signer, idx) => (
            <React.Fragment key={signer.uid}>
              {idx > 0 && <span className="separator">, </span>}
              <button
                className="metadata-value clickable"
                onClick={(e) => {
                  e.stopPropagation();
                  handleSignerClick(signer.uid);
                }}
              >
                {signer.first_name} {signer.last_name}
              </button>
            </React.Fragment>
          ))}
        </div>
      )}

      {/* Counterpart entities (all non-org entities from this decision) */}
      {counterpartEntities && counterpartEntities.length > 0 && (
        <div className="counterpart-entities">
          <div className="counterpart-entities-title">
            {t('decisionCard.counterpartEntities', 'Συνδεδεμένες οντότητες')}
          </div>
          {counterpartEntities.map((ent, idx) => (
            <button
              key={`${ent.entity.afm}-${ent.role}-${idx}`}
              className="counterpart-entity-item"
              onClick={() => handleEntityClick(ent.entity.afm)}
              title={t('decisionCard.viewEntityDetails')}
            >
              <span className="counterpart-entity-role">{ent.role}</span>
              <span className="counterpart-entity-name">
                {ent.entity.name || `AFM: ${ent.entity.afm}`}
              </span>
              {ent.total_amount > 0 && (
                <span className="counterpart-entity-amount">
                  {formatAmount(ent.total_amount)}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* External links */}
      <div className="document-actions">
        {decision.ada && (
          <a
            href={`https://diavgeia.gov.gr/decision/view/${decision.ada}`}
            target="_blank"
            rel="noopener noreferrer"
            className="document-link external"
            title={t('decisionCard.viewOnDiavgeia')}
          >
            <ExternalLinkIcon size={14} /> {decision.ada}
          </a>
        )}

        {decision.ada && (
          <a
            href={`https://diavgeia.gov.gr/doc/${decision.ada}?inline=true`}
            target="_blank"
            rel="noopener noreferrer"
            className="document-link view"
            title={t('decisionCard.viewOriginalDocument')}
          >
            <EyeIcon size={14} /> {t('decisionCard.viewDocument')}
          </a>
        )}

        {decision.document_url && (
          <a
            href={decision.document_url}
            target="_blank"
            rel="noopener noreferrer"
            className="document-link download"
            title={t('decisionCard.downloadOriginalDocument')}
          >
            <DownloadIcon size={14} /> {t('decisionCard.downloadDocument')}
          </a>
        )}
      </div>

      {/* ── Document Content (collapsible) ─────────────────────────── */}
      <CollapsibleCard
        title={
          <span className="dc-collapsible-title">
            <BookOpenIcon size={14} /> {t('decisionCard.documentContent')}
          </span>
        }
        subtitle={
          docStatus === 'COMPLETED' && docMeta ? (
            <span className="dc-collapsible-subtitle">
              {docMeta.character_count?.toLocaleString() || '?'} chars
              {docMeta.page_count != null && ` · ${docMeta.page_count}p`}
              {docMeta.extraction_provider && ` · ${docMeta.extraction_provider}`}
            </span>
          ) : null
        }
        defaultOpen={false}
        className="dc-collapsible dc-content-collapsible"
      >
        {docStatus === 'COMPLETED' && docContent ? (
          <div className="dc-collapsible-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {docContent}
            </ReactMarkdown>
          </div>
        ) : docStatus === 'PENDING' || docStatus === 'PROCESSING' ? (
          <div className="dc-collapsible-placeholder">
            <div className="spinner" /><p>{t('decisionCard.extractionInProgress')}</p>
          </div>
        ) : docStatus === 'FAILED' ? (
          <div className="dc-collapsible-placeholder">
            <AlertIcon size={20} />
            <p>{t('decisionCard.extractionFailed')}</p>
            <button className="document-link" onClick={handleRequestContent}>{t('decisionCard.retry')}</button>
          </div>
        ) : docStatus === 'NOT_FOUND' || !decision.has_document_content ? (
          <div className="dc-collapsible-placeholder">
            <BookOpenIcon size={20} />
            <p>{t('decisionCard.noDocumentContent')}</p>
            <button className="document-link" onClick={handleRequestContent}>{t('decisionCard.requestExtraction')}</button>
          </div>
        ) : docLoading ? (
          <div className="dc-collapsible-placeholder">
            <div className="spinner" /><p>{t('common.loading')}</p>
          </div>
        ) : null}
      </CollapsibleCard>

      {/* ── AI Summary (collapsible) ────────────────────────────────── */}
      <CollapsibleCard
        title={
          <span className="dc-collapsible-title">
            <SparklesIcon size={14} /> {t('decisionCard.aiSummary')}
          </span>
        }
        subtitle={
          aiStatus === 'COMPLETED' && aiMeta ? (
            <span className="dc-collapsible-subtitle">
              {aiMeta.model_used}
              {aiMeta.cost_usd && ` · $${aiMeta.cost_usd}`}
            </span>
          ) : null
        }
        defaultOpen={false}
        className="dc-collapsible dc-ai-collapsible"
      >
        {aiStatus === 'COMPLETED' && aiSummary ? (
          <div className="dc-collapsible-body">
            <div className="dc-ai-text">{aiSummary}</div>
          </div>
        ) : aiStatus === 'RUNNING' ? (
          <div className="dc-collapsible-placeholder">
            <div className="spinner" /><p>{t('decisionCard.aiSummaryRunning')}</p>
          </div>
        ) : aiStatus === 'FAILED' ? (
          <div className="dc-collapsible-placeholder">
            <AlertIcon size={20} />
            <p>{t('decisionCard.aiSummaryFailed')}</p>
            <button className="document-link" onClick={handleRequestAISummary}>{t('decisionCard.retry')}</button>
          </div>
        ) : aiStatus === 'NOT_FOUND' ? (
          <div className="dc-collapsible-placeholder">
            <SparklesIcon size={20} />
            <p>{t('decisionCard.noAISummary')}</p>
            <button className="document-link" onClick={handleRequestAISummary} disabled={aiRequesting}>
              {aiRequesting ? <LoaderIcon className="spinner" size={14} /> : <SearchIcon size={14} />}
              {' '}{t('decisionCard.requestAISummary')}
            </button>
          </div>
        ) : aiLoading ? (
          <div className="dc-collapsible-placeholder">
            <div className="spinner" /><p>{t('common.loading')}</p>
          </div>
        ) : null}
      </CollapsibleCard>

      {decision.kae_amounts && decision.kae_amounts.length > 1 && (
        <div className="kae-breakdown">
          <button
            className="kae-summary"
            onClick={() => setShowKae(!showKae)}
            aria-expanded={showKae}
          >
            <span>{t('decisionCard.viewKaeBreakdown', { count: decision.kae_amounts.length })}</span>
            {showKae ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          {showKae && (
            <div className="kae-content">
              {decision.kae_amounts.map((kae, kaeIndex) => (
                <div
                  key={kaeIndex}
                  className={`kae-item ${kaeIndex < decision.kae_amounts.length - 1 ? 'has-border' : ''}`}
                >
                  <span className="kae-code">KAE: {kae.kae}</span>
                  <span className="kae-amount">{formatAmount(kae.amount)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default DecisionCard;
