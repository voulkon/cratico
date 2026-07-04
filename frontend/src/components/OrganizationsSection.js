import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useDateRange } from '../contexts/DateRangeContext';
import useInfiniteScroll from '../hooks/useInfiniteScroll';
import apiClient from '../api/client';
import { CollapsibleSection, DashboardSectionLoading } from './DashboardGrid';
import { formatCompactAmount } from '../utils/format';

const PAGE_SIZE = 6;

/**
 * OrganizationsSection — Infinite-scroll list of most active organizations.
 *
 * Fetches from /explore/organizations/ with offset-based pagination.
 * Uses useInfiniteScroll to auto-load more as the user scrolls.
 */
const OrganizationsSection = ({
  onSeeAll,
  collapsible = false,
  className = '',
}) => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { dateRange } = useDateRange();

  const [organizations, setOrganizations] = useState([]);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  // Fetch a page of organizations (append mode after initial load)
  const fetchOrganizations = useCallback(async (offset, append = false) => {
    if (!dateRange) return;

    try {
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
        setError(null);
      }

      const response = await apiClient.get(
        `/explore/organizations/?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}&limit=${PAGE_SIZE}&offset=${offset}`
      );

      const data = response.data;

      if (append) {
        setOrganizations(prev => [...prev, ...(data.organizations || [])]);
      } else {
        setOrganizations(data.organizations || []);
      }

      setHasMore(data.has_more ?? false);
    } catch (err) {
      console.error('Failed to load organizations:', err);
      if (!append) setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [dateRange]);

  // Reset and reload when dateRange changes
  useEffect(() => {
    setOrganizations([]);
    setHasMore(true);
    fetchOrganizations(0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateRange]);

  const loadMore = useCallback(() => {
    if (hasMore && !loadingMore && !loading) {
      fetchOrganizations(organizations.length, true);
    }
  }, [hasMore, loadingMore, loading, organizations.length, fetchOrganizations]);

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
        title={t('homepage.mostActiveOrganizations')}
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
      title={t('homepage.mostActiveOrganizations')}
      onSeeAll={organizations.length > 0 ? onSeeAll : undefined}
      collapsible={collapsible}
      className={className}
    >
      <div className="dashboard-section-info">
        <span>{organizations.length} {t('homepage.decisions')}</span>
      </div>
      <div className="dashboard-section-scroll">
        {organizations.length === 0 ? (
          <p className="dashboard-empty">{t('exploration.noResults')}</p>
        ) : (
          <>
            {organizations.map((org, index) => (
              <button
                key={org.uid}
                className="dashboard-item-card"
                onClick={() => navigate(`/entity/organization/${org.uid}`)}
              >
                <div className="dashboard-item-left">
                  <span className="dashboard-rank">#{index + 1}</span>
                </div>
                <div className="dashboard-item-body">
                  <div className="dashboard-item-title">
                    {org.label}
                  </div>
                  <div className="dashboard-item-meta">
                    <span>{org.count} {t('homepage.decisions')}</span>
                  </div>
                </div>
                <span className="dashboard-item-amount">{formatCompactAmount(org.total_amount)}</span>
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

export default OrganizationsSection;
