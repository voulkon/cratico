import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import TopBarSlot from '../components/TopBarSlot';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import './DecisionDetailPage.css';
import '../components/StatCard.css';
import EntityDisplay from '../components/EntityDisplay';
import { formatAmount, formatDate } from '../utils/dateUtils';
import { useDecisionAI } from '../hooks/useDecisionAI';
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
  DownloadIcon
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

  const { aiAnalysis, requestExtraction, requestAISummary } = useDecisionAI(decision, fetchDecisionData);

  const handleViewDocumentContent = async () => {
    try {
      const response = await apiClient.get(`/decision/${id}/content/`);

      if (response.data.content || response.data.raw_text) {
        const body = response.data.content || response.data.raw_text;
        const newWindow = window.open('', '_blank');
        newWindow.document.write(`
          <html>
            <head><title>${t('decisionDetail.documentTitle', { ada: decision.ada })}</title></head>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
              <h1>${t('decisionDetail.decisionLabel')} ${decision.ada}</h1>
              <h2>${decision.subject}</h2>
              <div style="white-space: pre-wrap; line-height: 1.6;">
                ${body}
              </div>
            </body>
          </html>
        `);
      } else {
        alert(t('decisionDetail.documentNotAvailable'));
      }
    } catch (error) {
      console.error('Error fetching document content:', error);
      alert(t('decisionDetail.documentContentError', { error: error.message }));
    }
  };

  const handleRequestContent = async () => {
    try {
      await requestExtraction();
      alert(t('decisionDetail.extractionQueued'));
    } catch (err) {
      alert(typeof err === 'string' ? err : t('decisionDetail.extractionFailed'));
    }
  };

  const handleRequestAISummary = async (force = false) => {
    try {
      await requestAISummary(force);
      alert(t('decisionDetail.aiSummaryQueued'));
    } catch (err) {
      alert(typeof err === 'string' ? err : t('decisionDetail.aiSummaryFailed'));
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

  const hasTimeline = decision.publish_timestamp || decision.submission_timestamp;

  return (
    <div className="decision-detail-page">
      {/* Top-bar decision header (rendered via TopBarSlot portal) —
          always keeps the current decision visible in the fixed top bar */}
      <TopBarSlot>
        <div className="entity-header-topbar">
          <span className="entity-title-topbar">{decision.subject}</span>
          <span className="entity-subtitle-topbar">
            {t('decisionDetail.decisionLabel')} {decision.ada}
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

        <h1 className="decision-title">{decision.subject}</h1>

        {/* Metadata demoted to hover tooltips on compact chips */}
        <div className="decision-metadata">
          {decision.ada && (
            <span
              className="meta-chip meta-chip--ada"
              title={`${t('decisionDetail.versionId')}: ${decision.version_id || '—'}`}
            >
              ADA: {decision.ada}
            </span>
          )}
          <span
            className={`meta-chip status-badge status-${(decision.status || '').toLowerCase()}`}
            title={t('decisionDetail.statusLabel')}
          >
            {decision.status}
          </span>
          {decision.protocol_number && (
            <span
              className="meta-chip protocol-badge"
              title={t('decisionDetail.protocol')}
            >
              {t('decisionDetail.protocol')}: {decision.protocol_number}
            </span>
          )}
        </div>
      </div>

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

      {/* Core Information — stat cards (StatisticsGrid outline) */}
      <div className="statistics-grid decision-stats-grid">
        <div className="stat-card">
          <h3 className="stat-title">
            <CalendarIcon size={16} /> {t('decisionDetail.timeline')}
          </h3>
          <div className="stat-value date-range">
            {formatDate(decision.issue_date)}
          </div>
          {hasTimeline && (
            <div className="stat-context timeline-lines">
              {decision.publish_timestamp && (
                <div>
                  <strong>{t('decisionDetail.published')}:</strong>{' '}
                  {formatDate(decision.publish_timestamp)}
                </div>
              )}
              {decision.submission_timestamp && (
                <div>
                  <strong>{t('decisionDetail.submitted')}:</strong>{' '}
                  {formatDate(decision.submission_timestamp)}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="stat-card">
          <h3 className="stat-title">
            <DocumentTypeIcon size={16} /> {t('decisionDetail.decisionType')}
          </h3>
          {decision.decision_type ? (
            <div className="stat-context decision-type-text">
              {decision.decision_type.label}
            </div>
          ) : (
            <div className="stat-context no-data">
              {t('decisionDetail.typeNotSpecified')}
            </div>
          )}
        </div>

        <div className="stat-card">
          <h3 className="stat-title">
            <FinancialIcon size={16} /> {t('decisionDetail.financialInformation')}
          </h3>
          <div className="stat-value">{formatAmount(decision.amount)}</div>
          <div className="stat-context">
            {decision.financial_year && (
              <span>{t('decisionDetail.financialYear')} {decision.financial_year}</span>
            )}
            {decision.currency && decision.currency !== 'EUR' && (
              <span> · {decision.currency}</span>
            )}
          </div>
        </div>
      </div>

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

          {decision.has_document_content ? (
            <button
              className="document-link"
              onClick={handleViewDocumentContent}
              title={t('decisionDetail.viewExtractedContentTooltip')}
            >
              <BookOpenIcon size={15} /> {t('decisionDetail.viewExtractedContent')}
            </button>
          ) : (
            <button
              className="document-link document-link--request"
              onClick={handleRequestContent}
              title={t('decisionDetail.requestContentTooltip')}
            >
              <BookOpenIcon size={15} /> {t('decisionDetail.requestContent')}
            </button>
          )}
        </div>

        {decision.attachments && decision.attachments.length > 0 && (
          <div className="attachments-list">
            <h4><PaperclipIcon size={16} /> {t('decisionDetail.attachments', { count: decision.attachments.length })}</h4>
            {decision.attachments.map((attachment, index) => (
              <div key={index} className="attachment-item">
                <span className="attachment-icon"><PaperclipIcon size={14} /></span>
                <span className="attachment-name">{attachment.filename}</span>
                <span className="attachment-type">({attachment.mime_type})</span>
              </div>
            ))}
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

      {/* AI Analysis Section */}
      <div className="section-block ai-analysis-section">
        <h3 className="section-heading">
          <SearchIcon size={20} /> {t('decisionDetail.aiAnalysis')}
        </h3>

        {aiAnalysis?.status === 'COMPLETED' && aiAnalysis.summary ? (
          <div className="ai-summary-result">
            <div className="ai-summary-text">{aiAnalysis.summary}</div>
            <div className="ai-summary-meta">
              {aiAnalysis.model_used && <span>{t('decisionDetail.aiModel')}: {aiAnalysis.model_used}</span>}
              {aiAnalysis.cost_usd && <span>{t('decisionDetail.aiCost')}: ${aiAnalysis.cost_usd}</span>}
              {aiAnalysis.completed_at && <span>{formatDate(aiAnalysis.completed_at)}</span>}
            </div>
            <div className="ai-action-buttons">
              <button className="document-link" onClick={() => handleRequestAISummary(true)}>
                {t('decisionDetail.retryAISummary')}
              </button>
            </div>
          </div>
        ) : aiAnalysis?.status === 'RUNNING' ? (
          <div className="ai-summary-status">
            <div className="spinner" />
            <p>{t('decisionDetail.aiSummaryRunning')}</p>
          </div>
        ) : aiAnalysis?.status === 'FAILED' ? (
          <div className="ai-summary-status ai-summary-failed">
            <p>{t('decisionDetail.aiSummaryFailed')}: {aiAnalysis.error_message}</p>
            <button className="document-link" onClick={() => handleRequestAISummary(true)}>
              {t('decisionDetail.retryAISummary')}
            </button>
          </div>
        ) : (
          <div className="ai-summary-actions">
            <p className="section-description">{t('decisionDetail.aiAnalysisDescription')}</p>
            <div className="ai-action-buttons">
              {!decision.has_document_content && (
                <button
                  className="document-link"
                  onClick={handleRequestContent}
                  title={t('decisionDetail.requestContentTooltip')}
                >
                  <BookOpenIcon size={15} /> {t('decisionDetail.requestContent')}
                </button>
              )}
              <button
                className="document-link document-link--ai"
                onClick={handleRequestAISummary}
                title={t('decisionDetail.requestAISummaryTooltip')}
              >
                <SearchIcon size={15} /> {t('decisionDetail.requestAISummary')}
              </button>
            </div>
          </div>
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
                  {related.amount && (
                    <span className="related-amount">
                      €{related.amount.toLocaleString()}
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
