import React from 'react';
import PropTypes from 'prop-types';
import { CalendarIcon, ChartIcon, FileIcon } from './Icons';
import { RefreshCw } from 'lucide-react';
import { useTranslation } from '../contexts/TranslationContext';
import './SubscriptionMetadataHeader.css';

/**
 * Displays subscription-wide metadata for viewing all decisions across batches.
 * Shows subscription details, filters, and summary statistics.
 *
 * Used by: SubscriptionHistoryPage
 */
const SubscriptionMetadataHeader = ({
  subscription,
  totalBatches,
  totalDecisions,
  dateRange,
  formatDate,
  formatAmount,
  title
}) => {
  const { t } = useTranslation();

  if (!subscription) {
    return null;
  }

  const {
    alias,
    organization_label,
    entity_name,
    entity_afm,
    keywords,
    keyword_match_operator,
    amount_min,
    amount_max,
    decision_types,
    check_frequency,
    created_at,
    last_checked
  } = subscription;

  // Determine subscription target display
  const getSubscriptionTarget = () => {
    if (organization_label) {
      return `${t('notifications.organizationPrefix')} ${organization_label}`;
    }
    if (entity_name) {
      return `${t('notifications.entityPrefix')} ${entity_name}${entity_afm ? ` (${t('notifications.afmPrefix')} ${entity_afm})` : ''}`;
    }
    return t('notifications.noTargetSpecified');
  };

  // Check if any filters are applied
  const hasFilters = keywords?.length > 0 || amount_min || amount_max || decision_types?.length > 0;

  return (
    <div className="subscription-metadata-header">
      {/* Title */}
      <h1 className="subscription-title">{title || t('notifications.subscriptionHistory')}</h1>

      {/* Subscription Name and Target */}
      <div className="subscription-primary-info">
        <div className="subscription-name-section">
          {alias && (
            <h2 className="subscription-alias">{alias}</h2>
          )}
          <div className="subscription-target">{getSubscriptionTarget()}</div>
        </div>

        {check_frequency && (
          <div className="check-frequency-badge">
            <RefreshCw className="frequency-icon" size={16} />
            <span className="frequency-text">{check_frequency}</span>
          </div>
        )}
      </div>

      {/* Filters Applied */}
      {hasFilters && (
        <div className="filters-section">
          <h3 className="filters-title">{t('notifications.activeFilters')}</h3>
          <div className="filters-grid">
            {keywords && keywords.length > 0 && (
              <div className="filter-item">
                <div className="filter-label">{t('notifications.keywords')}</div>
                <div className="filter-value">
                  <div className="keywords-list">
                    {keywords.map((keyword, index) => (
                      <span key={index} className="keyword-badge">{keyword}</span>
                    ))}
                  </div>
                  {keyword_match_operator && (
                    <span className="match-operator">{keyword_match_operator === 'AND' ? t('notifications.allKeywordsRequired') : t('notifications.anyKeywordMatches')}</span>
                  )}
                </div>
              </div>
            )}

            {(amount_min || amount_max) && (
              <div className="filter-item">
                <div className="filter-label">{t('filters.amountRange')}</div>
                <div className="filter-value">
                  {amount_min && amount_max
                    ? `${formatAmount ? formatAmount(amount_min) : amount_min} - ${formatAmount ? formatAmount(amount_max) : amount_max}`
                    : amount_min
                    ? `≥ ${formatAmount ? formatAmount(amount_min) : amount_min}`
                    : `≤ ${formatAmount ? formatAmount(amount_max) : amount_max}`
                  }
                </div>
              </div>
            )}

            {decision_types && decision_types.length > 0 && (
              <div className="filter-item">
                <div className="filter-label">{t('filters.decisionTypes')}</div>
                <div className="filter-value">
                  <div className="types-list">
                    {decision_types.map((type, index) => (
                      <span key={index} className="type-badge">{type}</span>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Summary Statistics */}
      <div className="subscription-stats-section">
        <h3 className="stats-title">{t('notifications.overview')}</h3>
        <div className="stats-grid">
          <div className="stat-card stat-card-icon-layout">
            <ChartIcon className="stat-icon" size={32} />
            <div className="stat-content">
              <div className="stat-value">{totalBatches || 0}</div>
              <div className="stat-label">{t('notifications.totalBatches')}</div>
            </div>
          </div>

          <div className="stat-card stat-card-icon-layout">
            <FileIcon className="stat-icon" size={32} />
            <div className="stat-content">
              <div className="stat-value">{totalDecisions || 0}</div>
              <div className="stat-label">{t('notifications.totalDecisions')}</div>
            </div>
          </div>

          {dateRange && (dateRange.from || dateRange.to) && (
            <div className="stat-card stat-card-icon-layout wide">
              <CalendarIcon className="stat-icon" size={32} />
              <div className="stat-content">
                <div className="stat-label">{t('notifications.dateRange')}</div>
                <div className="stat-value date-range">
                  {dateRange.from && dateRange.to ? (
                    <>
                      {formatDate(dateRange.from)} <span className="arrow">→</span> {formatDate(dateRange.to)}
                    </>
                  ) : dateRange.from ? (
                    `${t('notifications.since')} ${formatDate(dateRange.from)}`
                  ) : dateRange.to ? (
                    `${t('notifications.until')} ${formatDate(dateRange.to)}`
                  ) : null}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Metadata Footer */}
      <div className="subscription-metadata-footer">
        {created_at && (
          <div className="metadata-item">
            <span className="metadata-label">{t('notifications.created')}:</span>
            <span className="metadata-value">{formatDate(created_at)}</span>
          </div>
        )}
        {last_checked && (
          <div className="metadata-item">
            <span className="metadata-label">{t('notifications.lastChecked')}:</span>
            <span className="metadata-value">{formatDate(last_checked)}</span>
          </div>
        )}
      </div>
    </div>
  );
};

SubscriptionMetadataHeader.propTypes = {
  subscription: PropTypes.shape({
    id: PropTypes.number,
    alias: PropTypes.string,
    organization_label: PropTypes.string,
    entity_name: PropTypes.string,
    entity_afm: PropTypes.string,
    keywords: PropTypes.arrayOf(PropTypes.string),
    keyword_match_operator: PropTypes.string,
    amount_min: PropTypes.number,
    amount_max: PropTypes.number,
    decision_types: PropTypes.arrayOf(PropTypes.string),
    check_frequency: PropTypes.string,
    created_at: PropTypes.string,
    last_checked: PropTypes.string
  }),

  totalBatches: PropTypes.number,
  totalDecisions: PropTypes.number,

  dateRange: PropTypes.shape({
    from: PropTypes.string,
    to: PropTypes.string
  }),

  formatDate: PropTypes.func.isRequired,
  formatAmount: PropTypes.func,

  title: PropTypes.string
};

export default SubscriptionMetadataHeader;
