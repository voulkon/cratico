import React, { useState, useEffect, useRef, useCallback, useContext, createContext } from 'react';
import { useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import { useTranslation } from '../contexts/TranslationContext';
import { OrganizationIcon, EntityIcon } from './Icons';
import './TopCounterparts.css'; // Reuse the same styles

// Import DateRangeContext if available; fall back to a dummy context
// so useContext is always called unconditionally (rules-of-hooks).
let DateRangeContext;
try {
  DateRangeContext = require('../contexts/DateRangeContext').DateRangeContext;
} catch (e) {
  DateRangeContext = createContext(); // dummy — useContext will return undefined
}

/**
 * Component to display top Org×Entity relationship pairs
 * Supports both general relationships and direct assignments
 * Can work standalone or with DateRangeContext
 */
const TopRelationshipPairs = ({
  dateRange: propDateRange, // Optional: override context date range
  limit = 20, // Items per page
  showDirectAssignmentsToggle = true,
  defaultDirectAssignmentsOnly = true,
  enableInfiniteScroll = true, // Enable/disable infinite scrolling
  className = '', // Optional: additional class for grid integration
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // useContext always called unconditionally; returns undefined when provider is absent
  const contextDateRange = useContext(DateRangeContext)?.dateRange;

  // Use prop dateRange if provided, otherwise fall back to context
  const dateRange = propDateRange || contextDateRange;

  const [results, setResults] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
  const [directAssignmentsOnly, setDirectAssignmentsOnly] = useState(defaultDirectAssignmentsOnly);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);

  const observerTarget = useRef(null);

  // Reset state when filters change
  useEffect(() => {
    setResults([]);
    setOffset(0);
    setHasMore(true);
    setError(null);
  }, [dateRange, directAssignmentsOnly]);

  // Fetch function that can be called for initial load and pagination
  const fetchTopPairs = useCallback(async (currentOffset, isLoadingMore = false) => {
    if (!dateRange || !dateRange.start_date || !dateRange.end_date) {
      setLoading(false);
      return;
    }

    try {
      if (isLoadingMore) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      setError(null);

      let response;

      if (directAssignmentsOnly) {
        // Use direct assignments endpoint
        const params = new URLSearchParams({
          start_date: dateRange.start_date,
          end_date: dateRange.end_date,
          limit: limit,
          offset: currentOffset
        });

        response = await apiClient.get(`/direct-assignments/top-pairs/?${params}`);

        const newResults = response.data.results.map(item => ({
          'decision__organization__uid': item.organization.uid,
          'decision__organization__label': item.organization.label,
          'entity__afm': item.entity.afm,
          'entity__name': item.entity.name,
          'entity__entity_type': item.entity.entity_type,
          'total_amount': parseFloat(item.total_amount),
          'decision_count': item.decision_count
        }));

        // For direct assignments, we need to check if we got fewer results than limit
        // Note: The API might not return total_count, so we infer hasMore from results length
        const receivedCount = newResults.length;
        setHasMore(receivedCount === limit);

        if (isLoadingMore) {
          setResults(prev => [...prev, ...newResults]);
        } else {
          setResults(newResults);
          setTotalCount(receivedCount); // Update as we go
        }
      } else {
        // Use general relationships endpoint
        const params = new URLSearchParams({
          start_date: dateRange.start_date,
          end_date: dateRange.end_date,
          limit: limit,
          offset: currentOffset
        });

        response = await apiClient.get(`/explore/temporal/top-relationships/?${params}`);

        const newResults = response.data.results;
        const total = response.data.pagination.total_count;

        setTotalCount(total);
        setHasMore(currentOffset + newResults.length < total);

        if (isLoadingMore) {
          setResults(prev => [...prev, ...newResults]);
        } else {
          setResults(newResults);
        }
      }
    } catch (err) {
      console.error('Error fetching top relationship pairs:', err);
      setError(err.message);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [dateRange, limit, directAssignmentsOnly]);

  // Initial load
  useEffect(() => {
    fetchTopPairs(0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateRange, limit, directAssignmentsOnly]);

  // Load more function
  const loadMore = useCallback(() => {
    if (!loadingMore && hasMore && !loading) {
      const newOffset = offset + limit;
      setOffset(newOffset);
      fetchTopPairs(newOffset, true);
    }
  }, [loadingMore, hasMore, loading, offset, limit, fetchTopPairs]);

  // Infinite scroll observer
  useEffect(() => {
    if (!enableInfiniteScroll) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore && !loading) {
          loadMore();
        }
      },
      { threshold: 0.1 }
    );

    const currentTarget = observerTarget.current;
    if (currentTarget) {
      observer.observe(currentTarget);
    }

    return () => {
      if (currentTarget) {
        observer.unobserve(currentTarget);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enableInfiniteScroll, hasMore, loadingMore, loading, offset]);

  const formatAmount = (amount) => {
    if (!amount || amount === 0) return t('common.noAmount');
    return `€${amount.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`;
  };

  const handlePairClick = (pair) => {
    // Navigate to relationship page
    const orgUid = pair['decision__organization__uid'];
    const entityAfm = pair['entity__afm'];
    navigate(
      `/relationship/entity/${entityAfm}/org/${orgUid}?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}`
    );
  };

  const rootClass = className || 'top-counterparts-section data-section';

  if (error || !results || results.length === 0) {
    if (loading) {
      return (
        <div className={rootClass}>
          <h3 className="section-title">
            {t('relationships.topPairs')}
          </h3>
          <div className="counterparts-loading">{t('common.loading')}...</div>
        </div>
      );
    }
    return null; // Don't show section if no data
  }

  return (
    <div className={rootClass}>
      <div className="section-header">
        <h3 className="section-title">{t('relationships.topPairs')}</h3>
        {showDirectAssignmentsToggle && (
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={directAssignmentsOnly}
              onChange={(e) => setDirectAssignmentsOnly(e.target.checked)}
            />
            <span className="toggle-slider"></span>
            <span className="toggle-label">
              {t('filters.directAssignmentsOnly') || 'Direct Assignments Only'}
            </span>
          </label>
        )}
      </div>

      <div className="counterparts-info">
        <span className="info-text">
          {directAssignmentsOnly || !totalCount
            ? `${results.length} ${t('relationships.pairs') || 'pairs'}`
            : `${results.length} ${t('common.of')} ${totalCount}`
          }
        </span>
      </div>

      <div className="counterparts-scroll-container">
        {results.map((pair, index) => {
          const orgUid = pair['decision__organization__uid'];
          const orgLabel = pair['decision__organization__label'];
          const entityAfm = pair['entity__afm'];
          const entityName = pair['entity__name'];

          return (
            <button
              key={`${orgUid}-${entityAfm}-${index}`}
              className="counterpart-card relationship-pair-card"
              onClick={() => handlePairClick(pair)}
            >
              <div className="counterpart-header">
                <span className="counterpart-rank">#{index + 1}</span>
                <div className="pair-names">
                  <div className="pair-org">
                    <span className="pair-label">
                      <OrganizationIcon size={16} className="pair-icon" /> {orgLabel}
                    </span>
                    <span className="pair-id">{t('relationships.uidLabel')}: {orgUid}</span>
                  </div>
                  <div className="pair-connector">⇄</div>
                  <div className="pair-entity">
                    <span className="pair-label">
                      <EntityIcon size={16} className="pair-icon" /> {entityName}
                    </span>
                    <span className="pair-id">{t('relationships.afmLabel')}: {entityAfm}</span>
                  </div>
                </div>
              </div>
              <div className="counterpart-stats">
                <div className="stat-item">
                  <span className="stat-label">{t('counterparts.totalAmount')}</span>
                  <span className="stat-value amount">{formatAmount(pair.total_amount)}</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label">{t('counterparts.decisions')}</span>
                  <span className="stat-value count">{pair.decision_count}</span>
                </div>
              </div>
            </button>
          );
        })}

        {/* Loading indicator for pagination */}
        {loadingMore && (
          <div className="counterparts-loading-more">
            <div className="spinner-small"></div>
            <span>{t('common.loadingMore') || 'Loading more...'}</span>
          </div>
        )}

        {/* Infinite scroll trigger */}
        {enableInfiniteScroll && hasMore && !loadingMore && (
          <div ref={observerTarget} style={{ height: '20px', margin: '10px 0' }} />
        )}

        {/* Manual load more button when infinite scroll is disabled */}
        {hasMore && !enableInfiniteScroll && (
          <button
            className="load-more-button"
            onClick={loadMore}
            disabled={loadingMore}
          >
            {loadingMore ? t('common.loading') : t('common.loadMore') || 'Load More'}
          </button>
        )}
      </div>
    </div>
  );
};

export default TopRelationshipPairs;
