import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useDateRange } from '../contexts/DateRangeContext';
import useInfiniteScroll from '../hooks/useInfiniteScroll';
import useDecisionsList from '../hooks/useDecisionsList';
import { CollapsibleSection, DashboardSectionLoading } from './DashboardGrid';
import { formatCompactAmount } from '../utils/format';

const PAGE_SIZE = 5;

/**
 * DecisionsSection — Infinite-scroll list of notable recent decisions.
 *
 * Uses useDecisionsList hook which handles page-based pagination
 * against /explore/decisions-optimized/.  The sentinel triggers
 * loadMore() when scrolled into view.
 */
const DecisionsSection = ({
  onSeeAll,
  collapsible = false,
  className = '',
}) => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { dateRange } = useDateRange();

  // Build stable params for useDecisionsList — useMemo avoids
  // referential changes that would trigger re-fetches.
  const params = useMemo(() => ({
    start_date: dateRange?.start_date || '',
    end_date: dateRange?.end_date || '',
    sort_by: 'entity_amount_desc',
  }), [dateRange?.start_date, dateRange?.end_date]);

  const {
    decisions,
    pagination,
    loading,
    loadingMore,
    error,
    loadMore,
  } = useDecisionsList({
    endpoint: '/explore/decisions-optimized/',
    params,
    enabled: !!dateRange,
    pageSize: PAGE_SIZE,
  });

  const { sentinelRef } = useInfiniteScroll({
    hasMore: pagination?.has_next ?? false,
    loading,
    loadingMore,
    onLoadMore: loadMore,
  });

  if (loading) {
    return <DashboardSectionLoading message={t('homepage.loading')} />;
  }

  if (error) {
    return (
      <CollapsibleSection
        title={t('homepage.notableRecentDecisions')}
        onSeeAll={onSeeAll}
        collapsible={collapsible}
        className={className}
      >
        <div className="dashboard-section-info">
          <span className="error-text">{error}</span>
        </div>
      </CollapsibleSection>
    );
  }

  return (
    <CollapsibleSection
      title={t('homepage.notableRecentDecisions')}
      onSeeAll={decisions.length > 0 ? onSeeAll : undefined}
      collapsible={collapsible}
      className={className}
    >
      <div className="dashboard-section-info">
        <span>{decisions.length} {t('homepage.decisions')}</span>
      </div>
      <div className="dashboard-section-scroll">
        {decisions.length === 0 ? (
          <p className="dashboard-empty">{t('exploration.noResults')}</p>
        ) : (
          <>
            {decisions.map((decision, index) => (
              <button
                key={decision.ada}
                className="dashboard-item-card"
                onClick={() => navigate(`/decision/${decision.id}`)}
              >
                <span className="dashboard-rank">#{index + 1}</span>
                <div className="dashboard-item-body">
                  <div className="dashboard-item-title">
                    {decision.subject?.length > 80
                      ? `${decision.subject.substring(0, 80)}...`
                      : decision.subject}
                  </div>
                  <div className="dashboard-item-subtitle">
                    {decision.organization?.label?.length > 40
                      ? `${decision.organization.label.substring(0, 40)}...`
                      : decision.organization?.label}
                  </div>
                </div>
                <span className="dashboard-item-amount">{formatCompactAmount(decision.amount)}</span>
              </button>
            ))}

            {/* Infinite-scroll sentinel */}
            {pagination?.has_next && (
              <div ref={sentinelRef} className="dashboard-scroll-sentinel">
                {loadingMore && (
                  <div className="dashboard-loading-more">
                    <div className="spinner-small" />
                    <span>{t('homepage.loading')}</span>
                  </div>
                )}
              </div>
            )}

            {/* Manual "Load more" fallback */}
            {pagination?.has_next && !loadingMore && (
              <button
                className="dashboard-load-more"
                onClick={loadMore}
              >
                {t('exploration.loadMore')}
              </button>
            )}
          </>
        )}
      </div>
    </CollapsibleSection>
  );
};

export default DecisionsSection;
