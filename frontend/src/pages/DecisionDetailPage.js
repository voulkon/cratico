import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import { useTranslation } from '../contexts/TranslationContext';
import './DecisionDetailPage.css';
import EntityDisplay from '../components/EntityDisplay';
import { formatAmount } from '../utils/dateUtils';
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
  WrenchIcon
} from '../components/Icons';

const DecisionDetailPage = () => {
  const { ada: id } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [decision, setDecision] = useState(null);
  const [entityRelationships, setEntityRelationships] = useState([]);
  const [relatedDecisions, setRelatedDecisions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchDecisionData();
  }, [id]);

  const fetchDecisionData = async () => {
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
  };

  const handleViewDocumentContent = async () => {
    try {
      const response = await apiClient.get(`/decision/${id}/content/`);

      if (response.data.content) {
        const newWindow = window.open('', '_blank');
        newWindow.document.write(`
          <html>
            <head><title>${t('decisionDetail.documentTitle', { ada: decision.ada })}</title></head>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
              <h1>${t('decisionDetail.decisionLabel')} ${decision.ada}</h1>
              <h2>${decision.subject}</h2>
              <div style="white-space: pre-wrap; line-height: 1.6;">
                ${response.data.content}
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

  if (loading) {
    return (
      <div className="loading-container">
        <h2>{t('decisionDetail.loadingDecision')}</h2>
        <div className="spinner"></div>
      </div>
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
      {/* Header Section */}
      <div className="decision-header">
        <div className="breadcrumb">
          <button onClick={() => navigate(-1)} className="breadcrumb-link">
            {t('navigation.back')}
          </button>
          <span className="breadcrumb-separator">•</span>
          <span>{t('decisionDetail.decisionDetails')}</span>
        </div>

        <h1 className="decision-title">{decision.subject}</h1>

        <div className="decision-metadata">
          <span className="ada-badge">ADA: {decision.ada}</span>
          <span className="id-badge">ID: {decision.id}</span>
          <span className={`status-badge status-${decision.status.toLowerCase()}`}>
            {decision.status}
          </span>
          {decision.protocol_number && (
            <span className="protocol-badge">
              {t('decisionDetail.protocol')}: {decision.protocol_number}
            </span>
          )}
        </div>
      </div>

      {/* Core Information Grid */}
      <div className="decision-info-grid">
        <div className="info-card">
          <h3><FinancialIcon size={20} /> {t('decisionDetail.financialInformation')}</h3>
          {decision.amount && (
            <div className="amount-display">
              {formatAmount(decision.amount)}
            </div>
          )}
          {decision.currency && decision.currency !== 'EUR' && (
            <div className="currency-info">
              {t('decisionDetail.currency')}: {decision.currency}
            </div>
          )}
          {decision.financial_year && (
            <div className="financial-year">
              {t('decisionDetail.financialYear')}: {decision.financial_year}
            </div>
          )}
        </div>

        <div className="info-card">
          <h3><CalendarIcon size={20} /> {t('decisionDetail.timeline')}</h3>
          <div className="timeline-item">
            <strong>{t('decisionDetail.issueDate')}:</strong> {new Date(decision.issue_date).toLocaleDateString('en-GB', {
              day: '2-digit',
              month: '2-digit',
              year: 'numeric'
            })}
          </div>
          {decision.publish_timestamp && (
            <div className="timeline-item">
              <strong>{t('decisionDetail.published')}:</strong> {new Date(decision.publish_timestamp).toLocaleDateString('en-GB', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric'
              })}
            </div>
          )}
          {decision.submission_timestamp && (
            <div className="timeline-item">
              <strong>{t('decisionDetail.submitted')}:</strong> {new Date(decision.submission_timestamp).toLocaleDateString('en-GB', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric'
              })}
            </div>
          )}
        </div>

        <div className="info-card">
          <h3><DocumentTypeIcon size={20} /> {t('decisionDetail.decisionType')}</h3>
          {decision.decision_type ? (
            <button
              className="clickable-entity decision-type-button"
              onClick={() => navigate(`/explore/type/${decision.decision_type.uid}`)}
              title={t('decisionDetail.exploreDecisionsOfType')}
            >
              {decision.decision_type.label}
            </button>
          ) : (
            <span className="no-data">{t('decisionDetail.typeNotSpecified')}</span>
          )}
        </div>
      </div>

      {/* Organizational Context */}
      <div className="organizational-section">
        <h3><OrganizationIcon size={20} /> {t('decisionDetail.organizationalContext')}</h3>

        {decision.organization && (
          <div className="org-info">
            <h4>{t('decisionDetail.issuingOrganization')}</h4>
            <button
              className="clickable-entity org-link"
              onClick={() => navigate(`/entity/organization/${decision.organization.uid}`)}
              title={t('decisionDetail.viewOrganizationDetails')}
            >
              <OrganizationIcon size={16} /> {decision.organization.label}
            </button>

            <button
              className="org-chart-quick-link"
              onClick={() => navigate(`/organizations?uid=${decision.organization.uid}`)}
              title={t('decisionDetail.viewOrganizationChart')}
            >
              <ChartIcon size={16} /> {t('decisionDetail.viewOrgChart')}
            </button>
          </div>
        )}

        {decision.signers && decision.signers.length > 0 && (
          <div className="signers-section">
            <h4><UsersIcon size={18} /> {t('decisionDetail.signers', { count: decision.signers.length })}</h4>
            <div className="signers-grid">
              {decision.signers.map(signer => (
                <button
                  key={signer.uid}
                  className="clickable-entity signer-card"
                  onClick={() => navigate(`/entity/signer/${signer.uid}`)}
                  title={t('decisionDetail.viewSignerDetails')}
                >
                  <UserIcon size={16} /> {signer.first_name} {signer.last_name}
                </button>
              ))}
            </div>
          </div>
        )}

        {decision.units && decision.units.length > 0 && (
          <div className="units-section">
            <h4><OrganizationIcon size={18} /> {t('decisionDetail.organizationalUnits', { count: decision.units.length })}</h4>
            <div className="units-list">
              {decision.units.map(unit => (
                <button
                  key={unit.uid}
                  className="clickable-entity unit-tag"
                  onClick={() => navigate(`/entity/unit/${unit.uid}`)}
                  title={t('decisionDetail.viewUnitDetails')}
                >
                  <OrganizationIcon size={16} /> {unit.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Entity Relationships */}
      {entityRelationships && entityRelationships.length > 0 && (
        <div className="entities-section">
          <h3><LinkIcon size={20} /> {t('decisionDetail.relatedEntities')}</h3>
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

      {/* Document Section */}
      <div className="document-section">
        <h3><FileIcon size={20} /> {t('decisionDetail.documents')}</h3>

        <div className="document-actions">
          {decision.document_url && (
            <button
              className="document-link primary-doc"
              onClick={() => window.open(decision.document_url, '_blank')}
              title={t('decisionDetail.viewOriginalDocumentTooltip')}
            >
              <FileIcon size={16} /> {t('decisionDetail.viewOriginalDocument')}
            </button>
          )}

          <button
            className="document-link extracted-content"
            onClick={handleViewDocumentContent}
            title={t('decisionDetail.viewExtractedContentTooltip')}
          >
            <BookOpenIcon size={16} /> {t('decisionDetail.viewExtractedContent')}
          </button>

          {decision.url && (
            <button
              className="document-link diavgeia-link"
              onClick={() => window.open(decision.url, '_blank')}
              title={t('decisionDetail.viewOnDiavgeiaTooltip')}
            >
              <GlobeIcon size={16} /> {t('decisionDetail.viewOnDiavgeia')}
            </button>
          )}
        </div>

        {decision.attachments && decision.attachments.length > 0 && (
          <div className="attachments-list">
            <h4><PaperclipIcon size={18} /> {t('decisionDetail.attachments', { count: decision.attachments.length })}</h4>
            {decision.attachments.map((attachment, index) => (
              <div key={index} className="attachment-item">
                <span className="attachment-icon"><PaperclipIcon size={14} /></span>
                <span className="attachment-name">{attachment.filename}</span>
                <span className="attachment-type">({attachment.mime_type})</span>
                {attachment.checksum && (
                  <span className="attachment-checksum" title={t('decisionDetail.fileChecksum')}>
                    {attachment.checksum.substring(0, 8)}...
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        {decision.document_checksum && (
          <div className="document-checksum">
            <small>{t('decisionDetail.documentChecksum')}: {decision.document_checksum}</small>
          </div>
        )}
      </div>

      {/* Related Decisions */}
      {relatedDecisions && relatedDecisions.length > 0 && (
        <div className="related-decisions">
          <h3><SearchIcon size={20} /> {t('decisionDetail.relatedDecisions')}</h3>
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
                  {new Date(related.issue_date).toLocaleDateString('en-GB')}
                  {related.decision_type && (
                    <span> • {related.decision_type.label}</span>
                  )}
                </div>
              </button>
            ))}
          </div>

          {relatedDecisions.length > 6 && (
            <div className="related-more">
              <button
                className="view-more-related"
                onClick={() => navigate(`/entity/organization/${decision.organization.uid}`)}
              >
                {t('decisionDetail.viewAllFromOrganization')} →
              </button>
            </div>
          )}
        </div>
      )}

      {/* Debug Info (only in development) */}
      {process.env.NODE_ENV === 'development' && (
        <div className="debug-section">
          <details>
            <summary><WrenchIcon size={16} /> {t('decisionDetail.debugInformation')}</summary>
            <div className="debug-content">
              <p><strong>{t('decisionDetail.decisionId')}:</strong> {decision.id}</p>
              <p><strong>ADA:</strong> {decision.ada}</p>
              <p><strong>{t('decisionDetail.versionId')}:</strong> {decision.version_id}</p>
              {decision.corrected_version_id && (
                <p><strong>{t('decisionDetail.correctedVersion')}:</strong> {decision.corrected_version_id}</p>
              )}
              {decision.warnings && (
                <p><strong>{t('decisionDetail.warnings')}:</strong> {decision.warnings}</p>
              )}
            </div>
          </details>
        </div>
      )}
    </div>
  );
};

export default DecisionDetailPage;
