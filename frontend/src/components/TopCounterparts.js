import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import relationshipsApi from '../api/relationshipsApi';
import { useTranslation } from '../contexts/TranslationContext';
import useTopCounterparts from '../hooks/useTopCounterparts';
import useInfiniteScroll from '../hooks/useInfiniteScroll';
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
  onCounterpartClick // callback: (counterpart) => void - parent controls navigation URL
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const isOrg = type === 'organization';

  // ── Organization path: useTopCounterparts hook (infinite scroll + search) ──
  const hook = useTopCounterparts({
    orgId: isOrg ? id : null,
    dateRange,
    pageSize: limit,
    enabled: isOrg && !!id && !!dateRange,
  });

  // ── Entity path: simple single-fetch (backward compatible) ──
  const [entityData, setEntityData] = useState(null);
  const [entityLoading, setEntityLoading] = useState(false);
  const [entityError, setEntityError] = useState(null);

  useEffect(() => {
    if (isOrg || !id || !dateRange) return;
    const fetchEntity = async () => {
      setEntityLoading(true);
      setEntityError(null);
      try {
        const params = {
          start_date: dateRange.start_date || dateRange.startDate,
          end_date: dateRange.end_date || dateRange.endDate,
          limit,
        };
        const result = await relationshipsApi.getTopOrganizations(id, params);
        setEntityData(result);
      } catch (err) {
        console.error('Error fetching top organizations:', err);
        setEntityError(err.message);
      } finally {
        setEntityLoading(false);
      }
    };
    fetchEntity();
  }, [isOrg, id, dateRange?.start_date, dateRange?.end_date, limit]);

  // ── Unified data ──
  const results = isOrg ? hook.results : (entityData?.results || []);
  const loading = isOrg ? hook.loading : entityLoading;
  const error = isOrg ? hook.error : entityError;
  const totalCount = isOrg ? hook.totalCount : (entityData?.pagination?.total_count || 0);
  const { hasMore, loadingMore, loadMore, searchQuery, setSearchQuery } = hook;

  const { sentinelRef } = useInfiniteScroll({
    hasMore,
    loading,
    loadingMore,
    onLoadMore: loadMore,
    enabled: isOrg,
  });

  const formatAmount = (amount) => {
    if (!amount || amount === 0) return t('common.noAmount');
    return `€${amount.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`;
  };

  const handleCounterpartClick = (counterpart) => {
    if (onCounterpartClick) {
      onCounterpartClick(counterpart);
      return;
    }
    if (type === 'entity') {
      const orgUid = counterpart.decision__organization__uid;
      navigate(`/relationship/entity/${id}/org/${orgUid}?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}`);
    } else if (type === 'organization') {
      const afm = counterpart.entity__afm;
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
  return (
    <div className="top-counterparts-section">
      <div className="section-header">
        <h3 className="section-title">{title}</h3>
      </div>

      {/* Search input (organizations only) */}
      {isOrg && (
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
      )}

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
              : counterpart.entity__name;
            const identifier = type === 'entity'
              ? counterpart.decision__organization__uid
              : counterpart.entity__afm;
            const entityType = type === 'organization' ? counterpart.entity__entity_type : null;

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
                <div className="counterpart-stats">
                  <div className="stat-item">
                    <span className="stat-label">{t('counterparts.totalAmount')}</span>
                    <span className="stat-value amount">{formatAmount(counterpart.total_amount)}</span>
                  </div>
                  <div className="stat-item">
                    <span className="stat-label">{t('counterparts.decisions')}</span>
                    <span className="stat-value count">{counterpart.decision_count}</span>
                  </div>
                </div>
              </button>
            );
          })}

          {/* Infinite-scroll sentinel */}
          {isOrg && <div ref={sentinelRef} className="scroll-sentinel" />}
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
  );
};

export default TopCounterparts;
