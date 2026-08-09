import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useDateRange } from '../contexts/DateRangeContext';
import useInfiniteScroll from '../hooks/useInfiniteScroll';
import apiClient from '../api/client';
import { CollapsibleSection, DashboardSectionLoading } from './DashboardGrid';
import { formatCompactAmount } from '../utils/format';

const PAGE_SIZE = 5;

/**
 * TopDirectAssignmentsSection — Highest-amount direct-assignment decisions.
 *
 * Infinite-scroll ranked list. Fetches from /decisions/top-direct-assignments/
 * with limit/offset pagination and appends pages as the user scrolls.
 */
const TopDirectAssignmentsSection = ({
  onSeeAll,
  collapsible = false,
  className = '',
}) => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { dateRange } = useDateRange();

  const [decisions, setDecisions] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  // Fetch a page of decisions (append mode after the initial load).
  const fetchDecisions = useCallback(async (offset, append = false) => {
    if (!dateRange) return;

    try {
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
        setError(null);
      }

      const response = await apiClient.get(
        `/decisions/top-direct-assignments/?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}&limit=${PAGE_SIZE}&offset=${offset}`
      );

      const data = response.data;

      if (append) {
        setDecisions(prev => [...prev, ...(data.results || [])]);
      } else {
        setDecisions(data.results || []);
      }

      setTotalCount(data.pagination?.total_count ?? 0);
      setHasMore(data.pagination?.has_next ?? false);
    } catch (err) {
      console.error('Failed to load top direct assignments:', err);
      if (!append) setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [dateRange]);

  // Reset and reload when the date range changes.
  useEffect(() => {
    setDecisions([]);
    setTotalCount(0);
    setHasMore(true);
    fetchDecisions(0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateRange]);

  const loadMore = useCallback(() => {
    if (hasMore && !loadingMore && !loading) {
      fetchDecisions(decisions.length, true);
    }
  }, [hasMore, loadingMore, loading, decisions.length, fetchDecisions]);

  const { sentinelRef } = useInfiniteScroll({
    hasMore,
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
        title={t('homepage.highestDirectAssignments')}
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
      title={t('homepage.highestDirectAssignments')}
      onSeeAll={decisions.length > 0 ? onSeeAll : undefined}
      collapsible={collapsible}
      className={className}
    >
      <div className="dashboard-section-info">
        <span>{totalCount} {t('homepage.decisions')}</span>
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
                <div className="dashboard-item-left">
                  <span className="dashboard-rank">#{index + 1}</span>
                </div>
                <div className="dashboard-item-body">
                  <div className="dashboard-item-title">
                    {decision.subject}
                  </div>
                  <div className="dashboard-item-subtitle">
                    {decision.organization?.label}
                    {decision.main_recipient?.name && (
                      <> → {decision.main_recipient.name}</>
                    )}
                  </div>
                </div>
                <span className="dashboard-item-amount">{formatCompactAmount(decision.amount)}</span>
              </button>
            ))}

            {/* Infinite-scroll sentinel */}
            {hasMore && (
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
            {hasMore && !loadingMore && (
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

export default TopDirectAssignmentsSection;
