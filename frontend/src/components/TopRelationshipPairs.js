import React, { useState, useEffect, useRef, useCallback, useContext, createContext } from 'react';
import { useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import { useTranslation } from '../contexts/TranslationContext';
import { OrganizationIcon, EntityIcon } from './Icons';
import CounterpartStats from './CounterpartStats';
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
  collapsible = false, // If true, section header acts as a collapse toggle
  defaultCollapsed = false, // Initial collapsed state (only when collapsible)
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
  const [sectionCollapsed, setSectionCollapsed] = useState(defaultCollapsed);

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

        // Map general-endpoint keys to the same shape the render code expects
        const newResults = response.data.results.map(item => ({
          'decision__organization__uid': item.organization_uid,
          'decision__organization__label': item.organization_label,
          'entity__afm': item.entity_afm,
          'entity__name': item.entity_name,
          'entity__entity_type': item.entity_type,
          'total_amount': parseFloat(item.total_amount),
          'decision_count': item.decision_count
        }));
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

  const handlePairClick = (pair) => {
    // Navigate to relationship page
    const orgUid = pair['decision__organization__uid'];
    const entityAfm = pair['entity__afm'];
    navigate(
      `/relationship/entity/${entityAfm}/org/${orgUid}?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}`
    );
  };

  const rootClass = className || 'top-counterparts-section data-section';

  const handleSectionToggle = () => {
    setSectionCollapsed((prev) => !prev);
  };

  if (error || !results || results.length === 0) {
    // Debug: log what triggered the early-return so we know why the section
    // might disappear when the toggle is clicked.
    if (process.env.NODE_ENV === 'development') {
      console.debug('[TopRelationshipPairs] early-return decision', {
        hasError: !!error,
        errorMessage: error || null,
        resultsIsNullish: results == null,
        resultsLength: results?.length ?? null,
        loading,
        directAssignmentsOnly,
        dateRange,
      });
    }

    if (loading) {
      return (
        <div className={rootClass}>
          <div className="section-header">
            {collapsible && (
              <button
                className="dashboard-section-collapse-toggle"
                onClick={handleSectionToggle}
                aria-expanded={!sectionCollapsed}
                title={sectionCollapsed ? 'Expand section' : 'Collapse section'}
              >
                <span
                  className={`dashboard-collapse-chevron${sectionCollapsed ? ' dashboard-collapse-chevron--collapsed' : ''}`}
                  aria-hidden="true"
                />
              </button>
            )}
            <h3 className="section-title">
              {t('relationships.topPairs')}
            </h3>
          </div>
          {!sectionCollapsed && (
            <div className="counterparts-loading">{t('common.loading')}...</div>
          )}
        </div>
      );
    }

    // Show empty state instead of returning null — preserves the section
    // header with the toggle so the user can switch back.
    return (
      <div className={rootClass}>
        <div className="section-header">
          {collapsible && (
            <button
              className="dashboard-section-collapse-toggle"
              onClick={handleSectionToggle}
              aria-expanded={!sectionCollapsed}
              title={sectionCollapsed ? 'Expand section' : 'Collapse section'}
            >
              <span
                className={`dashboard-collapse-chevron${sectionCollapsed ? ' dashboard-collapse-chevron--collapsed' : ''}`}
                aria-hidden="true"
              />
            </button>
          )}
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
        {!sectionCollapsed && (
          <div className="counterparts-loading">
            {error
              ? `${t('common.error') || 'Error'}: ${error}`
              : t('common.noResults') || 'No results found for this filter.'}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={rootClass}>
      <div className="section-header">
        {collapsible && (
          <button
            className="dashboard-section-collapse-toggle"
            onClick={handleSectionToggle}
            aria-expanded={!sectionCollapsed}
            title={sectionCollapsed ? 'Expand section' : 'Collapse section'}
          >
            <span
              className={`dashboard-collapse-chevron${sectionCollapsed ? ' dashboard-collapse-chevron--collapsed' : ''}`}
              aria-hidden="true"
            />
          </button>
        )}
        <h3 className="section-title">{t('relationships.topPairs')}</h3>
        {!sectionCollapsed && showDirectAssignmentsToggle && (
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

      {!sectionCollapsed && (
        <>
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
                      <OrganizationIcon size={16} className="pair-icon" />
                      <span className="pair-label-text" title={orgLabel}>{orgLabel}</span>
                    </span>
                  </div>
                  <div className="pair-connector">⇄</div>
                  <div className="pair-entity">
                    <span className="pair-label">
                      <EntityIcon size={16} className="pair-icon" />
                      <span className="pair-label-text" title={entityName}>{entityName}</span>
                    </span>
                    <div className="pair-entity-details">
                      <span className="pair-id">{t('relationships.afmLabel')}: {entityAfm}</span>
                      {pair['entity__entity_type'] && (
                        <span className="pair-entity-type">{pair['entity__entity_type']}</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
              <CounterpartStats
                totalAmount={pair.total_amount}
                decisionCount={pair.decision_count}
              />
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
        </>
      )}
    </div>
  );
};

export default TopRelationshipPairs;
