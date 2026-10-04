import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useDateRange } from '../contexts/DateRangeContext';
import useInfiniteScroll from '../hooks/useInfiniteScroll';
import apiClient from '../api/client';
import { CollapsibleSection, DashboardSectionLoading } from './DashboardGrid';
import { formatCompactAmount } from '../utils/format';
import { buildEntityUrl } from '../utils/entityLinks';

const PAGE_SIZE = 5;

/**
 * TopBandedDaReceiversSection — Entities receiving the most €30k–€38k
 * direct assignments ("banded" = per-decision linked money-received total
 * inside the €30k–€38k window).
 *
 * Ranked by frequency (most assignments received first). Fetches from
 * /decisions/top-banded-da-receivers/ with limit/offset pagination and
 * appends pages as the user scrolls.
 */
const TopBandedDaReceiversSection = ({
  onSeeAll,
  collapsible = false,
  className = '',
  directOnly = false,
}) => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { dateRange } = useDateRange();

  const [rows, setRows] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  const fetchRows = useCallback(async (offset, append = false) => {
    if (!dateRange) return;

    try {
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
        setError(null);
      }

      const response = await apiClient.get(
        `/decisions/top-banded-da-receivers/?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}&limit=${PAGE_SIZE}&offset=${offset}`
      );

      const data = response.data;

      if (append) {
        setRows(prev => [...prev, ...(data.results || [])]);
      } else {
        setRows(data.results || []);
      }

      setTotalCount(data.pagination?.total_count ?? 0);
      setHasMore(data.pagination?.has_more ?? false);
    } catch (err) {
      console.error('Failed to load banded direct-assignment receivers:', err);
      if (!append) setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [dateRange]);

  useEffect(() => {
    setRows([]);
    setTotalCount(0);
    setHasMore(true);
    fetchRows(0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateRange]);

  const loadMore = useCallback(() => {
    if (hasMore && !loadingMore && !loading) {
      fetchRows(rows.length, true);
    }
  }, [hasMore, loadingMore, loading, rows.length, fetchRows]);

  const { sentinelRef } = useInfiniteScroll({
    hasMore,
    loading,
    loadingMore,
    onLoadMore: loadMore,
  });

  const title = t('homepage.repeatBandedDaReceivers');

  if (loading) {
    return <DashboardSectionLoading message={t('homepage.loading')} />;
  }

  if (error) {
    return (
      <CollapsibleSection
        title={title}
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
      title={title}
      onSeeAll={rows.length > 0 ? onSeeAll : undefined}
      collapsible={collapsible}
      className={className}
    >
      <div className="dashboard-section-info">
        <span>{totalCount} {t('homepage.recipients')}</span>
      </div>
      <div className="dashboard-section-scroll">
        {rows.length === 0 ? (
          <p className="dashboard-empty">{t('exploration.noResults')}</p>
        ) : (
          <>
            {rows.map((row, index) => (
              <button
                key={row.entity_afm}
                className="dashboard-item-card"
                onClick={() => navigate(buildEntityUrl('afm', row.entity_afm, dateRange, { directOnly }))}
              >
                <div className="dashboard-item-left">
                  <span className="dashboard-rank">#{index + 1}</span>
                </div>
                <div className="dashboard-item-body">
                  <div className="dashboard-item-title">
                    {row.entity_name}
                  </div>
                  <div className="dashboard-item-subtitle">
                    {row.decision_count} {t('homepage.assignments')}
                  </div>
                </div>
                <span className="dashboard-item-amount">
                  {formatCompactAmount(row.banded_amount_sum)}
                </span>
              </button>
            ))}

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

            {hasMore && !loadingMore && (
              <button className="dashboard-load-more" onClick={loadMore}>
                {t('exploration.loadMore')}
              </button>
            )}
          </>
        )}
      </div>
    </CollapsibleSection>
  );
};

export default TopBandedDaReceiversSection;
