import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import apiClient from '../api/client';
import './DecisionCard.css';

import {OrganizationIcon, PenIcon, CalendarIcon, EyeIcon, DownloadIcon, ExternalLinkIcon, BookOpenIcon, LoaderIcon, ChevronDown, ChevronUp} from './Icons.js';

import EntityDisplay from './EntityDisplay';
import { getMainRecipient, getTotalAmount, groupEntityRelationships, getCounterpartEntities } from '../utils/decisionUtils';
import { formatDate } from '../utils/dateUtils';



const DecisionCard = ({ decision, formatAmount, index, isLastItem, onViewDocumentContent }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [isLoadingContent, setIsLoadingContent] = useState(false);
  const [documentContent, setDocumentContent] = useState(null);
  const [showContent, setShowContent] = useState(false);
  const [entityRelationships, setEntityRelationships] = useState(null);
  const [showEntities, setShowEntities] = useState(false);
  const [loadingEntities, setLoadingEntities] = useState(false);
  const [showKae, setShowKae] = useState(false);

  // Check if entity data is already included in decision (from optimized endpoint)
  const hasPreloadedEntityData = decision.entity_amount !== undefined
    || decision.main_recipient !== undefined
    || decision.entities !== undefined;

  const handleViewContent = async () => {
    if (documentContent) {
      setShowContent(!showContent);
      return;
    }

    if (!onViewDocumentContent) {
      console.error('onViewDocumentContent function not provided');
      return;
    }

    setIsLoadingContent(true);
    try {
      const content = await onViewDocumentContent(decision.id);
      setDocumentContent(content);
      setShowContent(true);
    } catch (error) {
      console.error('Failed to fetch document content:', error);
    } finally {
      setIsLoadingContent(false);
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

      {/* Document Actions Section - Compact */}
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

        {decision.has_document_content && (
          <button
            onClick={handleViewContent}
            disabled={isLoadingContent}
            className="document-link content-button"
            title={showContent ? t('decisionCard.hideDocumentContent') : t('decisionCard.viewDocumentContent')}
          >
            {isLoadingContent ? <LoaderIcon className="spinner" size={14} /> : <BookOpenIcon size={14} />} {showContent ? t('decisionCard.hideText') : t('decisionCard.showText')}
          </button>
        )}
      </div>

      {/* Document Content Display */}
      {showContent && documentContent && (
        <div className="document-content-section">
          <div className="document-content">
            <div className="raw-text-container">
              <pre className="raw-text">{documentContent.raw_text}</pre>
            </div>
          </div>
        </div>
      )}

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
