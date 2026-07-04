import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { useTranslation } from '../contexts/TranslationContext';
import Chevron from './Chevron';
import './BatchMetadataHeader.css';

/**
 * Displays batch-specific metadata including check window, subscription info,
 * and aggregate statistics.
 *
 * Used by: NotificationBatchDetailPage
 */
const BatchMetadataHeader = ({
  batch,
  formatDate,
  formatAmount,
  showCheckWindow = true,
  showCreatedAt = true,
  showSubscriptionInfo = true,
  showStats = true,
  title,
  open: controlledOpen,
  onToggle,
  defaultOpen = true,
}) => {
  const { t } = useTranslation();

  // ── Collapsible state ─────────────────────────────────────────
  const [localOpen, setLocalOpen] = useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? !!controlledOpen : localOpen;

  const handleToggle = (e) => {
    const next = e.target.open;
    if (isControlled) onToggle?.(next);
    else setLocalOpen(next);
  };

  if (!batch) {
    return null;
  }

  const { subscription, check_window_start, check_window_end, created_at, match_count, aggregate_stats } = batch;

  const displayTitle = title || t('notifications.notificationBatch');

  return (
    <details className="batch-metadata-header" open={isOpen} onToggle={handleToggle}>
      <summary className="batch-metadata-summary">
        <span className="batch-metadata-summary-title">
          {displayTitle}
          {match_count > 0 && (
            <span className="batch-metadata-summary-count"> — {match_count} {t('notifications.totalMatches').toLowerCase()}</span>
          )}
        </span>
        <Chevron open={isOpen} />
      </summary>

      <div className="batch-metadata-content">
      {/* Subscription Info */}
      {showSubscriptionInfo && subscription && (
        <div className="subscription-info">
          <div className="info-label">{t('notifications.subscription')}</div>
          <div className="subscription-details">
            {subscription.alias && (
              <span className="subscription-alias">{subscription.alias}</span>
            )}
            {subscription.organization_label && (
              <span className="organization-label">
                {subscription.organization_label}
              </span>
            )}
            {subscription.entity_name && (
              <span className="entity-name">
                {subscription.entity_name}
                {subscription.entity_afm && (
                  <span className="entity-afm"> ({t('notifications.afmPrefix')} {subscription.entity_afm})</span>
                )}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Batch Metadata */}
      <div className="batch-metadata">
        {showCheckWindow && check_window_start && check_window_end && (
          <div className="metadata-item">
            <div className="metadata-label">{t('notifications.checkWindow')}</div>
            <div className="metadata-value">
              <span className="date-range">
                {formatDate(check_window_start)} → {formatDate(check_window_end)}
              </span>
            </div>
          </div>
        )}

        {showCreatedAt && created_at && (
          <div className="metadata-item">
            <div className="metadata-label">{t('notifications.created')}</div>
            <div className="metadata-value">{formatDate(created_at)}</div>
          </div>
        )}

        <div className="metadata-item">
          <div className="metadata-label">{t('notifications.totalMatches')}</div>
          <div className="metadata-value highlight">{match_count || 0}</div>
        </div>
      </div>

      {/* Aggregate Statistics */}
      {showStats && aggregate_stats && Object.keys(aggregate_stats).length > 0 && (
        <div className="statistics-section">
          <h3 className="statistics-title">{t('notifications.summaryStatistics')}</h3>
          <div className="statistics-grid">
            {aggregate_stats.total_amount !== undefined && (
              <div className="stat-card">
                <div className="stat-label">{t('notifications.totalAmount')}</div>
                <div className="stat-value">{formatAmount(aggregate_stats.total_amount)}</div>
              </div>
            )}

            {aggregate_stats.avg_amount !== undefined && (
              <div className="stat-card">
                <div className="stat-label">{t('notifications.avgAmount')}</div>
                <div className="stat-value">{formatAmount(aggregate_stats.avg_amount)}</div>
              </div>
            )}

            {aggregate_stats.max_amount !== undefined && (
              <div className="stat-card">
                <div className="stat-label">{t('notifications.maxAmount')}</div>
                <div className="stat-value">{formatAmount(aggregate_stats.max_amount)}</div>
              </div>
            )}

            {aggregate_stats.min_amount !== undefined && (
              <div className="stat-card">
                <div className="stat-label">{t('notifications.minAmount')}</div>
                <div className="stat-value">{formatAmount(aggregate_stats.min_amount)}</div>
              </div>
            )}

            {aggregate_stats.decision_type_counts && (
              <div className="stat-card full-width">
                <div className="stat-label">{t('notifications.decisionTypes')}</div>
                <div className="decision-types">
                  {Object.entries(aggregate_stats.decision_type_counts).map(([type, count]) => (
                    <span key={type} className="type-badge">
                      {type}: {count}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      </div>
    </details>
  );
};

BatchMetadataHeader.propTypes = {
  batch: PropTypes.shape({
    subscription: PropTypes.shape({
      alias: PropTypes.string,
      organization_label: PropTypes.string,
      entity_name: PropTypes.string,
      entity_afm: PropTypes.string
    }),
    check_window_start: PropTypes.string,
    check_window_end: PropTypes.string,
    created_at: PropTypes.string,
    match_count: PropTypes.number,
    aggregate_stats: PropTypes.object
  }).isRequired,

  formatDate: PropTypes.func.isRequired,
  formatAmount: PropTypes.func.isRequired,

  // Display toggles
  showCheckWindow: PropTypes.bool,
  showCreatedAt: PropTypes.bool,
  showSubscriptionInfo: PropTypes.bool,
  showStats: PropTypes.bool,

  // Optional title override
  title: PropTypes.string
};

export default BatchMetadataHeader;
