import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { NetworkIcon } from '../components/Icons';
import apiClient from '../api/client';
import TimeRangeSection from '../components/TimeRangeSection';
import TopCounterparts from '../components/TopCounterparts';
import TopRelationshipPairs from '../components/TopRelationshipPairs';
import DecisionList from '../components/DecisionList';
import DecisionsToolbar from '../components/DecisionsToolbar';
import CollapsibleCard from '../components/CollapsibleCard';
import StatisticsGrid from '../components/StatisticsGrid';
import useUrlFilters from '../hooks/useUrlFilters';
import useDocumentContent from '../hooks/useDocumentContent';
import useDecisionsList from '../hooks/useDecisionsList';
import useDecisionTypes from '../hooks/useDecisionTypes';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { createDynamicDateRangeUtils, formatAmount, toLocalISODate } from '../utils/dateUtils';
import { useTranslation } from '../contexts/TranslationContext';
import './EntityDetailPage.css';

const EntityDetailPage = () => {
  const { entityType, entityId, date, startDate, endDate, year, month, week } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();

  // Enhanced state to handle both modes
  const [entityData, setEntityData] = useState(null);

  useDocumentTitle(
    entityData?.name
      ? entityData.name
      : (entityType && entityId ? `${entityType}/${entityId}` : null)
  );

  // Determine exploration mode
  const explorationMode = location.pathname.startsWith('/explore') ? 'temporal' : 'entity';

  // Use URL filters hook for filter state management
  const {
    sortBy,
    searchQuery,
    selectedTypes: selectedDecisionTypes,
    selectedOrgs: organizationFilters,
    amountFilters,
    directAssignmentsOnly,
    activeFiltersCount,
    setSortBy,
    setSearchQuery,
    toggleType,
    setAmountFilters,
    setDirectAssignmentsOnly,
    clearAllFilters
  } = useUrlFilters({ sortBy: 'amount_desc' });

  const [statistics, setStatistics] = useState(null);
  const [statisticsLoading, setStatisticsLoading] = useState(false);
  const [statisticsError, setStatisticsError] = useState(null);
  const [error, setError] = useState(null);

  // Enhanced date range state
  const [entityDateRange, setEntityDateRange] = useState(null);
  const [dateRangeLoading, setDateRangeLoading] = useState(true);
  const [dynamicDateUtils, setDynamicDateUtils] = useState(null);
  const [timeRange, setTimeRange] = useState(null);
  const [monthRange, setMonthRange] = useState(null);

  // Decision type filtering state (via shared hook)
  const [isOrganizationsExpanded, setIsOrganizationsExpanded] = useState(true);
  const [isTimeRangeExpanded, setIsTimeRangeExpanded] = useState(true);
  const [temporalSummary, setTemporalSummary] = useState(null);

  const requiresManualStatistics = explorationMode === 'temporal' || (explorationMode === 'entity' && entityType === 'organization');
  const [statsRequested, setStatsRequested] = useState(!requiresManualStatistics);

  useEffect(() => {
    setStatsRequested(!requiresManualStatistics);
    setStatistics(null);
    setStatisticsError(null);
  }, [requiresManualStatistics]);

  // Parse temporal parameters into date range
  const parseTemporalDateRange = useCallback(() => {
    if (explorationMode !== 'temporal') return null;

    let startDateStr, endDateStr, label;

    if (date) {
      // Single day exploration: /explore/temporal/2025-05-31
      startDateStr = date;
      endDateStr = date;
      label = t('exploration.decisionsOn', { date: new Date(date).toLocaleDateString() });
    } else if (startDate && endDate) {
      // Date range exploration: /explore/temporal/2025-05-01/2025-05-31
      startDateStr = startDate;
      endDateStr = endDate;
      label = t('exploration.decisionsFrom', {
        startDate: new Date(startDate).toLocaleDateString(),
        endDate: new Date(endDate).toLocaleDateString()
      });
    } else if (year && month) {
      // Monthly exploration: /explore/month/2025/05
      const yearNum = parseInt(year);
      const monthNum = parseInt(month);
      const startOfMonth = new Date(yearNum, monthNum - 1, 1);
      const endOfMonth = new Date(yearNum, monthNum, 0);
      startDateStr = toLocalISODate(startOfMonth);
      endDateStr = toLocalISODate(endOfMonth);
      label = t('exploration.decisionsIn', {
        period: startOfMonth.toLocaleDateString('en-US', { year: 'numeric', month: 'long' })
      });
    } else if (year && week) {
      // Weekly exploration: /explore/week/2025/22
      const yearNum = parseInt(year);
      const weekNum = parseInt(week);
      // Calculate week start/end dates
      const jan1 = new Date(yearNum, 0, 1);
      const weekStart = new Date(jan1);
      weekStart.setDate(jan1.getDate() + (weekNum - 1) * 7 - jan1.getDay());
      const weekEnd = new Date(weekStart);
      weekEnd.setDate(weekStart.getDate() + 6);
      startDateStr = toLocalISODate(weekStart);
      endDateStr = toLocalISODate(weekEnd);
      label = t('exploration.week', { week: weekNum, year: yearNum });
    }

    return { startDateStr, endDateStr, label };
  }, [explorationMode, date, startDate, endDate, year, month, week, t]);

  // Debounced search query — declared before the effect that uses it.
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState(searchQuery);

  // Debounce search query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchQuery(searchQuery);
    }, 500);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  const { fetchContent: handleViewDocumentContent } = useDocumentContent();
  // Enhanced fetch functions for both modes
  const fetchEntityDateRange = useCallback(async () => {
    try {
      setDateRangeLoading(true);

      if (explorationMode === 'temporal') {
        // Temporal mode: derive time range directly from the URL.
        // No global /explore/date-range/ call — the URL fully defines
        // the range (day/week/month), and all other endpoints receive
        // start_date/end_date query params scoped to that range.
        const temporalRange = parseTemporalDateRange();
        if (temporalRange) {
          setTimeRange({
            startDate: temporalRange.startDateStr,
            endDate: temporalRange.endDateStr
          });
          // Minimal entityDateRange so the "no data" state doesn't
          // block rendering.  Data availability is verified by the
          // decisions endpoint itself (returns empty results if none).
          setEntityDateRange({ has_data: true });
        } else {
          setEntityDateRange({ has_data: false, message: 'Invalid temporal URL' });
        }
      } else {
        // Existing entity mode logic
        const response = await apiClient.get(
          `/entity/${entityType}/${entityId}/date-range/`
        );

        setEntityDateRange(response.data);

        // Populate entity metadata (name, type, etc.) from the date-range
        // response so the page title renders correctly even when full
        // statistics are deferred (e.g. for organizations).
        if (response.data.entity) {
          setEntityData(response.data.entity);
        }

        if (response.data.has_data) {
          const dateUtils = createDynamicDateRangeUtils(response.data);
          setDynamicDateUtils(dateUtils);

          const defaultRange = dateUtils.getProgressiveDefaultRange(
            response.data.activity_chart?.data
          );
          setMonthRange(defaultRange);
          setTimeRange({
            startDate: dateUtils.indexToDateString(defaultRange.startIndex),
            endDate: dateUtils.indexToDateString(defaultRange.endIndex, true)
          });
        }
      }

    } catch (err) {
      console.error('Failed to fetch date range:', err);
      setError(t('errors.failedToLoad'));
    } finally {
      setDateRangeLoading(false);
    }
  }, [explorationMode, entityType, entityId, parseTemporalDateRange, t]);

  // Decision-types endpoint for the current context (entity or temporal)
  const decisionTypesEndpoint = explorationMode === 'temporal'
    ? '/explore/decision-types/'
    : `/entity/${entityType}/${entityId}/decision-types/`;

  const { decisionTypes: availableDecisionTypes, loading: decisionTypesLoading } =
    useDecisionTypes({ endpoint: decisionTypesEndpoint, dateRange: timeRange });

  const fetchStatistics = useCallback(async () => {
    if (!timeRange) return;

    setStatisticsLoading(true);
    setStatisticsError(null);

    try {
      const params = new URLSearchParams({
        start_date: timeRange.startDate,
        end_date: timeRange.endDate
      });

      let endpoint;
      if (explorationMode === 'temporal') {
        endpoint = `/explore/statistics/?${params.toString()}`;
      } else {
        if (requiresManualStatistics) {
          params.append('lite', 'true');
        }
        endpoint = `/entity/${entityType}/${entityId}/statistics/?${params.toString()}`;
      }

      const response = await apiClient.get(endpoint, { timeout: 60000 });
      setStatistics(response.data);

      if (explorationMode === 'temporal') {
        setTemporalSummary(response.data);
      } else {
        setEntityData(response.data.entity);
      }
    } catch (err) {
      console.error('Failed to fetch statistics:', err);
      setStatisticsError(t('statistics.loadError'));
    } finally {
      setStatisticsLoading(false);
    }
  }, [explorationMode, entityType, entityId, timeRange, t, requiresManualStatistics]);

  // ── Unified decisions list hook ────────────────────────────────────────
  const decisionsEndpoint = explorationMode === 'temporal'
    ? '/explore/decisions-optimized/'
    : `/entity/${entityType}/${entityId}/decisions/`;

  const decisionsParams = {
    sort_by: sortBy,
    start_date: timeRange?.startDate,
    end_date: timeRange?.endDate,
    ...(debouncedSearchQuery.trim() && { q: debouncedSearchQuery.trim() }),
    ...(selectedDecisionTypes.length > 0 && { decision_types: selectedDecisionTypes.join(',') }),
    ...(amountFilters.minAmount && { min_amount: amountFilters.minAmount }),
    ...(amountFilters.maxAmount && { max_amount: amountFilters.maxAmount }),
    ...(explorationMode === 'temporal' && organizationFilters.length > 0 && { organization_ids: organizationFilters.join(',') }),
    ...(directAssignmentsOnly && { direct_assignments_only: 'true' }),
  };

  const {
    decisions,
    pagination,
    loading,
    loadingMore,
    loadMore,
  } = useDecisionsList({
    endpoint: decisionsEndpoint,
    params: decisionsParams,
    enabled: !!timeRange,
  });

  // Build a human-readable subtitle from metadata instead of showing the raw ID
  const getEntitySubtitle = useCallback(() => {
    const typeLabel = entityType.charAt(0).toUpperCase() + entityType.slice(1);

    if (!entityData?.metadata) {
      return `${typeLabel} • ${entityId}`;
    }

    const meta = entityData.metadata;

    if (entityType === 'organization') {
      const parts = [typeLabel];
      if (meta.category) parts.push(meta.category);
      if (meta.status) parts.push(meta.status);
      return parts.join(' • ');
    }

    if (entityType === 'afm') {
      const parts = [typeLabel];
      if (meta.entity_type) parts.push(meta.entity_type);
      if (meta.total_appearances != null) parts.push(`${meta.total_appearances} ${t('statistics.totalDecisions').toLowerCase()}`);
      return parts.join(' • ');
    }

    if (entityType === 'signer') {
      const parts = [typeLabel];
      if (meta.total_organizations != null) {
        parts.push(`${meta.total_organizations} ${t('statistics.organizationsCount').toLowerCase()}`);
      }
      return parts.join(' • ');
    }

    return `${typeLabel} • ${entityId}`;
  }, [entityType, entityId, entityData, t]);

  // Enhanced page title and breadcrumbs
  const getPageInfo = () => {
    if (explorationMode === 'temporal') {
      const temporalRange = parseTemporalDateRange();
      return {
        title: t('entityDetail.temporalExploration'),
        subtitle: temporalRange?.label || t('exploration.exploreByTimePeriod'),
        breadcrumb: t('entityDetail.exploreArrow') + ' ' + t('entityDetail.timeArrow')
      };
    } else {
      return {
        title: entityData?.name || entityId,
        subtitle: getEntitySubtitle(),
        breadcrumb: t('entityDetail.exploreArrow') + ' ' + t('entityDetail.entityArrow')
      };
    }
  };

  // Add handler for organization chart navigation
  const handleViewOrganizationChart = () => {
    console.log('Organization chart button clicked!');
    if (entityType === 'organization') {
      navigate(`/organizations?uid=${entityId}`);
    }
  };

  // Update URL params when filters change
  // Initial load: fetch date range
  useEffect(() => {
    const loadInitialData = async () => {
      setError(null);

      try {
        await fetchEntityDateRange();
      } catch (err) {
        setError(t('errors.failedToLoad'));
      }
    };

    loadInitialData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [explorationMode, entityType, entityId]);

  // Load decision types when time range changes (decisions are handled by useDecisionsList)
  // The useDecisionTypes hook auto-fetches on timeRange change, so nothing to do here.

  useEffect(() => {
    if (!timeRange || !statsRequested) return;
    // Non-blocking: statistics load independently from decision list/counterparts.
    fetchStatistics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeRange, sortBy, debouncedSearchQuery, selectedDecisionTypes, amountFilters, organizationFilters, statsRequested]);

  // Memoize dateRange for TopCounterparts to prevent duplicate fetches from
  // referentially-new inline objects on every render.
  const topCounterpartDateRange = useMemo(() => ({
    start_date: timeRange?.startDate,
    end_date: timeRange?.endDate,
  }), [timeRange?.startDate, timeRange?.endDate]);

  // Handlers
  const handleMonthRangeChange = (startIndex, endIndex) => {
    if (!dynamicDateUtils) return;

    setMonthRange({ startIndex, endIndex });
    setTimeRange({
      startDate: dynamicDateUtils.indexToDateString(startIndex),
      endDate: dynamicDateUtils.indexToDateString(endIndex, true)
    });
  };

  // Loading states (date range loading, or entity metadata not yet available while decisions are loading)
  if (dateRangeLoading || (loading && !entityData)) {
    return (
      <div style={{ padding: 'var(--spacing-xl)', textAlign: 'center' }}>
        {explorationMode === 'temporal' ? (
          <h2>{t('entityDetail.loadingTemporal')}</h2>
        ) : (
          <>
            <h2>{t('entityDetail.loadingEntity', { entityType })}</h2>
            <div>{t('entityDetail.loadingData', { entityId })}</div>
          </>
        )}
      </div>
    );
  }

  // No data state
  if (entityDateRange && !entityDateRange.has_data) {
    return (
      <div style={{ padding: 'var(--spacing-xl)' }}>
        <div style={{
          backgroundColor: '#fff3cd',
          border: '1px solid #ffeaa7',
          borderRadius: 'var(--radius-md)',
          padding: 'var(--spacing-xl)',
          marginTop: 'var(--spacing-xl)',
          textAlign: 'center'
        }}>
          <h2>{t('entityDetail.noDataAvailable')}</h2>
          <p>{entityDateRange.message}</p>
          {explorationMode === 'temporal' ? (
            <p>{t('entityDetail.noDataTemporal')}</p>
          ) : (
            <p>{t('entityDetail.entityLabel', { entityType, entityId })}</p>
          )}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 'var(--spacing-xl)' }}>
        <div style={{
          backgroundColor: '#ffe6e6',
          border: '1px solid #ff9999',
          borderRadius: 'var(--radius-sm)',
          padding: 'var(--spacing-md)',
          marginBottom: 'var(--spacing-xl)'
        }}>
          <strong>{t('common.error')}:</strong> {error}
        </div>
      </div>
    );
  }

  const pageInfo = getPageInfo();

  // Build statistics cards for StatisticsGrid component
  const statCards = statistics ? [
    {
      title: t('statistics.totalDecisions'),
      value: statistics.summary.decisions.total_count.toLocaleString(),
      subtitle: explorationMode === 'temporal'
        ? t('entityDetail.acrossOrganizations', { count: temporalSummary?.organizations_count || 0 })
        : undefined,
    },
    {
      title: t('statistics.totalAmount'),
      value: formatAmount(statistics.summary.financial.primary_amount),
      warning: statistics.summary.financial.has_discrepancy
        ? t('statistics.amountDiscrepancy', { percentage: statistics.summary.financial.discrepancy_percentage })
        : undefined,
    },
    ...(!requiresManualStatistics
      ? [{
          title: t('statistics.averageAmount'),
          value: formatAmount(statistics.summary.decisions.avg_amount),
        }]
      : []),
    {
      title: t('statistics.period'),
      value: t('statistics.days', { count: statistics.period.days_count }),
      subtitle: `${new Date(statistics.period.start_date).toLocaleDateString()} - ${new Date(statistics.period.end_date).toLocaleDateString()}`,
    },
  ] : null;

  return (
    <div className="entity-detail-page">
      <div className="entity-header">
        <div className="page-breadcrumb">{pageInfo.breadcrumb}</div>

        <div className="entity-title-row">
          <h1 className="entity-title">{pageInfo.title}</h1>
          {entityType === 'organization' && explorationMode !== 'temporal' && (
            <button
              onClick={handleViewOrganizationChart}
              className="org-chart-button-icon"
              title={t('entityDetail.viewOrganizationChart')}
              aria-label={t('entityDetail.viewOrganizationChart')}
            >
              <NetworkIcon />
            </button>
          )}
        </div>
        <div className="entity-subtitle">{pageInfo.subtitle}</div>

        {/* Signer Organizations and Positions - Collapsible */}
        {entityType === 'signer' && entityData?.metadata?.organizations && (
          <CollapsibleCard
            title={t('entityDetail.organizationsAndPositions')}
            subtitle={<> ({entityData.metadata.total_organizations} {t('entityDetail.organizationsCountLabel')}, {entityData.metadata.total_positions} {t('entityDetail.positionsCountLabel')})</>}
            open={isOrganizationsExpanded}
            onToggle={setIsOrganizationsExpanded}
            defaultOpen={true}
            className="signer-organizations-section"
          >
            <div className="section-content">
              <div className="organizations-grid">
                {entityData.metadata.organizations.map((orgData, index) => (
                  <div key={orgData.organization.uid} className="organization-card">
                    <div className="org-header">
                      <button
                        className="org-name clickable-entity"
                        onClick={() => navigate(`/entity/organization/${orgData.organization.uid}`)}
                        title={t('entityDetail.viewOrganizationDetails')}
                      >
                        <NetworkIcon /> {orgData.organization.label}
                      </button>
                      {orgData.decision_count && (
                        <span className="decision-count">
                          — {t('entityDetail.decisionsCount', { count: orgData.decision_count })}
                        </span>
                      )}
                    </div>

                    {orgData.positions && orgData.positions.length > 0 && (
                      <div className="positions-list">
                        <span className="positions-label">{t('entityDetail.positions')}:</span>
                        <div className="positions-tags">
                          {orgData.positions.map((position, posIndex) => (
                            <div
                              key={position.uid}
                              className={`position-tag ${position.status.toLowerCase()}`}
                            >
                              <span className="position-title">{position.label}</span>
                              {position.unit && (
                                <span className="position-unit">• {position.unit}</span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {orgData.latest_decision && (
                      <div className="org-activity">
                        <span className="activity-label">{t('entityDetail.lastActivity')}:</span>
                        <span className="activity-date">
                          {new Date(orgData.latest_decision).toLocaleDateString('en-GB', {
                            day: '2-digit',
                            month: '2-digit',
                            year: 'numeric'
                          })}
                        </span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </CollapsibleCard>
        )}

        {/* Enhanced time range - Collapsible */}
        {dynamicDateUtils && monthRange && (
          <TimeRangeSection
            dynamicDateUtils={dynamicDateUtils}
            monthRange={monthRange}
            onMonthRangeChange={handleMonthRangeChange}
            dateRange={entityDateRange.date_range}
            activityData={entityDateRange.activity_chart}
            summaryPrefix={explorationMode === 'temporal' ? t('exploration.globalData') : t('exploration.entityData')}
            showDateSpanInfo={true}
            open={isTimeRangeExpanded}
            onToggle={setIsTimeRangeExpanded}
          />
        )}
      </div>

      {/* Enhanced Statistics Cards for both modes */}
      {requiresManualStatistics && !statsRequested ? (
        <div className="statistics-manual-trigger" style={{ marginBottom: 'var(--spacing-xl)' }}>
          <button
            type="button"
            className="see-all-button"
            onClick={() => setStatsRequested(true)}
          >
            {t('entityDetail.loadStatistics', 'Load statistics')}
          </button>
        </div>
      ) : (
        <StatisticsGrid
          loading={statisticsLoading}
          error={statisticsError}
          cards={statCards}
          onRetry={fetchStatistics}
        />
      )}

      {/* Top Counterparts - Shows related entities/organizations */}
      {explorationMode === 'entity' && entityType === 'organization' && timeRange && (
        <TopCounterparts
          type="organization"
          id={entityId}
          dateRange={topCounterpartDateRange}
          limit={5}
          onCounterpartClick={(counterpart) => {
            const afm = counterpart.entity_afm;
            navigate(`/relationship/entity/${afm}/org/${entityId}?start_date=${timeRange.startDate}&end_date=${timeRange.endDate}`);
          }}
        />
      )}

      {/* Top Relationship Pairs - For temporal exploration, shows top Org×Entity combinations */}
      {explorationMode === 'temporal' && timeRange && (
        <TopRelationshipPairs
          dateRange={{
            start_date: timeRange.startDate,
            end_date: timeRange.endDate
          }}
          limit={10}
          collapsible
        />
      )}

      {/* Enhanced Filters Section for both modes */}
        <DecisionsToolbar
          title={explorationMode === 'temporal' ? t('entityDetail.allDecisions') : t('entityDetail.entityDecisions')}
          totalCount={pagination?.total_count}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          directOnly={directAssignmentsOnly}
          onDirectOnlyChange={setDirectAssignmentsOnly}
          sortBy={sortBy}
          onSortChange={setSortBy}
          sortVariant="simple"
          activeFiltersCount={activeFiltersCount}
          onClearAll={clearAllFilters}
          amountFilters={amountFilters}
          onAmountChange={(field, value) => setAmountFilters({ ...amountFilters, [field]: value })}
          decisionTypes={availableDecisionTypes}
          selectedTypes={selectedDecisionTypes}
          onTypeToggle={toggleType}
          typesLoading={decisionTypesLoading}
          pagination={pagination}
          extraFilters={explorationMode === 'temporal' ? (
            <div className="filter-group">
              <h4>{t('entityDetail.organizations')}</h4>
              {/* TODO: implement organization filter UI for temporal mode */}
              <div className="loading-text">
                {t('entityDetail.organizationFiltersComingSoon', 'Organization filters coming soon')}
              </div>
            </div>
          ) : null}
        >
          <DecisionList
            decisions={decisions}
            loading={loading}
            loadingMore={loadingMore}
            error={null}
            pagination={pagination}
            hasSearchQuery={!!(searchQuery || activeFiltersCount > 0)}
            formatAmount={formatAmount}
            onViewDocumentContent={handleViewDocumentContent}
            onLoadMore={loadMore}
            emptyMessage={t('entityDetail.noDecisionsFound')}
            infiniteScroll={true}
            getDecisionKey={(d) => d.ada}
          />
        </DecisionsToolbar>
    </div>
  );
};

export default EntityDetailPage;
