import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import useTopCounterparts from '../hooks/useTopCounterparts';
import useTopOrganizations from '../hooks/useTopOrganizations';
import useInfiniteScroll from '../hooks/useInfiniteScroll';
import CounterpartStats from './CounterpartStats';
import CollapsibleCard from './CollapsibleCard';
import './TopCounterparts.css';

/**
 * Reusable component to display top counterparts with infinite scroll and search.
 * For entities: shows top organizations
 * For organizations: shows top entities
 */
const TopCounterparts = ({
  type, // 'entity' or 'organization'
  id, // AFM for entity, UID for organization
  dateRange, // { start_date, end_date } — now stable via useMemo in parent
  limit = 10,
  onCounterpartClick, // callback: (counterpart) => void - parent controls navigation URL
  open: controlledOpen,
  onToggle,
  defaultOpen = true,
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const isOrg = type === 'organization';

  // ── Organization path: useTopCounterparts hook (infinite scroll + search) ──
  const orgHook = useTopCounterparts({
    orgId: isOrg ? id : null,
    dateRange,
    pageSize: limit,
    enabled: isOrg && !!id && !!dateRange,
  });

  // ── Entity path: useTopOrganizations hook (infinite scroll + search) ──
  const entityHook = useTopOrganizations({
    afm: !isOrg ? id : null,
    dateRange,
    pageSize: limit,
    enabled: !isOrg && !!id && !!dateRange,
  });

  // ── Unified data from the active hook ──
  const { results, loading, error, totalCount, hasMore, loadingMore, loadMore, searchQuery, setSearchQuery } =
    isOrg ? orgHook : entityHook;

  const { sentinelRef } = useInfiniteScroll({
    hasMore,
    loading,
    loadingMore,
    onLoadMore: loadMore,
    enabled: true,
  });

  const handleCounterpartClick = (counterpart) => {
    if (onCounterpartClick) {
      onCounterpartClick(counterpart);
      return;
    }
    if (type === 'entity') {
      const orgUid = counterpart.decision__organization__uid;
      navigate(`/relationship/entity/${id}/org/${orgUid}?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}`);
    } else if (type === 'organization') {
      const afm = counterpart.entity_afm;
      navigate(`/relationship/entity/${afm}/org/${id}?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}`);
    }
  };

  const title = type === 'entity'
    ? t('counterparts.topOrganizations')
    : t('counterparts.topEntities');

  // ── Loading state ──────────────────────────────────────────────
  if (loading) {
    return (
      <div className="top-counterparts-section">
        <h3 className="section-title">{title}</h3>
        <div className="counterparts-loading">{t('common.loading')}...</div>
      </div>
    );
  }

  // ── Error / empty state ────────────────────────────────────────
  if (error || results.length === 0) {
    return null;
  }

  // ── Normal render ──────────────────────────────────────────────
  const subtitle = totalCount > 0 ? <> ({totalCount.toLocaleString()})</> : null;

  return (
    <CollapsibleCard
      title={title}
      subtitle={subtitle}
      open={controlledOpen}
      onToggle={onToggle}
      defaultOpen={defaultOpen}
      className="top-counterparts-section"
    >
      <div className="top-counterparts-content">
      {/* Search input (both entity and organization paths) */}
      <div className="counterparts-search">
          <input
            type="text"
            className="counterparts-search-input"
            placeholder={t('counterparts.searchPlaceholder')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              className="counterparts-search-clear"
              onClick={() => setSearchQuery('')}
              aria-label={t('common.close')}
            >
              ×
            </button>
          )}
        </div>

      <div className="counterparts-info">
        {totalCount > 0 && (
          <span className="total-count-info">
            {t('counterparts.showing')} {results.length} {t('counterparts.of')} {totalCount}
          </span>
        )}
      </div>

      {/* Scrollable list with infinite scroll sentinel */}
      <div className="counterparts-scroll-container">
        <div className="counterparts-grid">
          {results.map((counterpart, index) => {
            const name = type === 'entity'
              ? counterpart.decision__organization__label
              : counterpart.entity_name;
            const identifier = type === 'entity'
              ? counterpart.decision__organization__uid
              : counterpart.entity_afm;
            const entityType = type === 'organization' ? counterpart.entity_type : null;

            return (
              <button
                key={`${identifier}-${index}`}
                className="counterpart-card"
                onClick={() => handleCounterpartClick(counterpart)}
              >
                <div className="counterpart-header">
                  <span className="counterpart-rank">#{index + 1}</span>
                  <span className="counterpart-name">{name}</span>
                </div>
                <div className="counterpart-details">
                  <span className="counterpart-id">
                    {type === 'entity' ? 'UID' : 'AFM'}: {identifier}
                  </span>
                  {entityType && (
                    <span className="entity-type-badge">{t(`entityTypes.${entityType}`)}</span>
                  )}
                </div>
                <CounterpartStats
                  totalAmount={counterpart.total_amount}
                  decisionCount={counterpart.decision_count}
                />
              </button>
            );
          })}

          {/* Infinite-scroll sentinel */}
          <div ref={sentinelRef} className="scroll-sentinel" />
        </div>

        {/* Loading-more indicator */}
        {loadingMore && (
          <div className="counterparts-loading-more">
            {t('common.loading')}...
          </div>
        )}

        {/* End-of-list indicator */}
        {!hasMore && results.length > 0 && (
          <div className="counterparts-end-message">
            {t('counterparts.allLoaded', { count: totalCount })}
          </div>
        )}
      </div>
      </div>
    </CollapsibleCard>
  );
};

export default TopCounterparts;
