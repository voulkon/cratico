import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import './EntityDisplay.css';

const EntityDisplay = ({
  entityRelationships,
  compact = false,
  showRoleBadge = true,
  showCompanies = false,  // New prop to control companies section visibility
  className = ''
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const handleEntityClick = (afm) => {
    navigate(`/entity/afm/${afm}`);
  };

  const formatAmount = (amount, currency = 'EUR') => {
      const currencySymbols = {
        EUR: '€',
        USD: '$',
        GBP: '£'
      };
    const symbol = currencySymbols[currency] || currency;
    return `${symbol}${parseFloat(amount).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`;
  };

  if (!entityRelationships || entityRelationships.length === 0) {
    return (
      <div className={`no-entities-message ${className}`}>
        {t('common.noRelatedEntities')}
      </div>
    );
  }

  return (
    <div className={`entities-grid ${compact ? 'compact' : ''} ${className}`}>
      {entityRelationships.map((rel, index) => (
        <div key={index} className={`entity-relationship ${compact ? 'compact' : ''}`}>
          {showRoleBadge && (
            <div className="entity-role-badge">
              {rel.role}
              {rel.occurrences > 1 && (
                <span className="occurrence-count">×{rel.occurrences}</span>
              )}
            </div>
          )}

          <button
            className="clickable-entity entity-link"
            onClick={() => handleEntityClick(rel.entity.afm)}
            title={t('common.viewEntityDecisions', { entityType: rel.entity.entity_type })}
          >
            <div className="entity-info">
              <div className="entity-name">
                {rel.entity.name || `AFM: ${rel.entity.afm}`}
              </div>
              <div className="entity-meta">
                <div className="entity-left-meta">
                  <span className="entity-afm">AFM: {rel.entity.afm}</span>
                </div>
                {rel.total_amount && (
                  <div className="entity-amount">
                    <span className="amount-value">
                      {formatAmount(
                        rel.total_amount.amount ?? rel.total_amount,
                        rel.total_amount.currency ?? 'EUR'
                        )}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </button>

          {rel.confidence_score && rel.confidence_score < 1.0 && (
            <div className="confidence-indicator" title={t('common.confidence', { percentage: (rel.confidence_score * 100).toFixed(0) })}>
              ~{(rel.confidence_score * 100).toFixed(0)}%
            </div>
          )}

          {showCompanies && !compact && rel.companies && rel.companies.length > 0 && (
            <div className="companies-info">
              <div className="companies-label">
                {t('common.associatedCompanies', { count: rel.companies.length })}
              </div>
              {rel.companies.map((company, companyIndex) => (
                <div key={company.ar_gemi || companyIndex} className="company-item">
                  <button
                    className="clickable-entity company-link"
                    onClick={() => navigate(`/entity/afm/${company.afm}`)}
                    title={t('common.viewCompanyDetails')}
                  >
                    <div className="company-name">{company.co_name_el || company.co_names_en?.[0]}</div>
                    <div className="company-details">
                      {company.legal_type_name && <span className="company-type">{company.legal_type_name}</span>}
                      {company.city && <span className="company-location">📍 {company.city}</span>}
                      {company.status_name && <span className="company-status">({company.status_name})</span>}
                    </div>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
};

export default EntityDisplay;
