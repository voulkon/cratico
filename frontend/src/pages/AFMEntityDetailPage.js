import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import useUrlFilters from '../hooks/useUrlFilters';
import useDocumentContent from '../hooks/useDocumentContent';
import useDecisionsList from '../hooks/useDecisionsList';
import useDecisionTypes from '../hooks/useDecisionTypes';
import TopCounterparts from '../components/TopCounterparts';
import TopBarSlot from '../components/TopBarSlot';
import GemiSection from '../components/GemiSection';
import DecisionList from '../components/DecisionList';
import DecisionsToolbar from '../components/DecisionsToolbar';
import StatisticsGrid from '../components/StatisticsGrid';
import TimeRangeSection from '../components/TimeRangeSection';
import { createDynamicDateRangeUtils, formatAmount } from '../utils/dateUtils';
import './AFMEntityDetailPage.css';

const AFMEntityDetailPage = () => {
  const { afm } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [entity, setEntity] = useState(null);
  useDocumentTitle(entity?.name || `AFM ${afm}`);
  const [statistics, setStatistics] = useState(null);
  const [error, setError] = useState(null);
  const [companyInfo, setCompanyInfo] = useState(null);
  const [gemiFetchStatus, setGemiFetchStatus] = useState(null); // null | 'loading' | 'queued' | 'already_queued' | 'already_fetched' | 'rate_limited' | 'error'

  // Enhanced date range state
  const [entityDateRange, setEntityDateRange] = useState(null);
  const [dateRangeLoading, setDateRangeLoading] = useState(true);
  const [dynamicDateUtils, setDynamicDateUtils] = useState(null);
  const [timeRange, setTimeRange] = useState(null);
  const [monthRange, setMonthRange] = useState(null);

  // Statistics state (non-blocking)
  const [statisticsLoading, setStatisticsLoading] = useState(false);
  const [statisticsError, setStatisticsError] = useState(null);
  const [statsRequested, setStatsRequested] = useState(false);

  // Use URL filters hook - replaces all the manual URL state management
  const {
    sortBy,
    searchQuery,
    selectedTypes: selectedDecisionTypes,
    amountFilters,
    directAssignmentsOnly,
    activeFiltersCount,
    setSortBy,
    setSearchQuery,
    toggleType,
    setAmountFilters,
    setDirectAssignmentsOnly,
    clearAllFilters,
    updateUrl
  } = useUrlFilters({ sortBy: 'amount_desc' });

  // Debounced search query
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState(searchQuery);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearchQuery(searchQuery), 500);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Decision types for this AFM (scans entire queryset, not just loaded batch)
  const { decisionTypes: availableDecisionTypes, loading: decisionTypesLoading } =
    useDecisionTypes({
      endpoint: '/decisions/unified/',
      extraParams: { source: 'afm', afm, view: 'decision_types' },
      dateRange: timeRange,
    });

  // ── Unified decisions list hook ────────────────────────────────────────
  const {
    decisions,
    pagination,
    loading,
    loadingMore,
    loadMore,
  } = useDecisionsList({
    endpoint: '/decisions/unified/',
    params: {
      source: 'afm',
      view: 'decisions',
      afm,
      sort_by: sortBy,
      start_date: timeRange?.startDate,
      end_date: timeRange?.endDate,
      ...(directAssignmentsOnly && { direct_assignments_only: 'true' }),
      ...(debouncedSearchQuery.trim() && { q: debouncedSearchQuery.trim() }),
      ...(selectedDecisionTypes.length > 0 && { decision_types: selectedDecisionTypes.join(',') }),
      ...(amountFilters.minAmount && { min_amount: amountFilters.minAmount }),
      ...(amountFilters.maxAmount && { max_amount: amountFilters.maxAmount }),
    },
    enabled: !!timeRange,
  });

  // ── Fetch entity metadata (name, type, roles) - fast, blocks nothing else
  const fetchEntityMetadata = useCallback(async () => {
    try {
      const entityResponse = await apiClient.get(`/entity/afm/${afm}/`);
      setEntity(entityResponse.data.entity);
    } catch (err) {
      console.error('Failed to fetch entity metadata:', err);
      setError(err.response?.data?.error || err.message);
    }
  }, [afm]);

  // Fetch date range for slider - fast, separate from decisions
  const fetchDateRange = useCallback(async () => {
    setDateRangeLoading(true);
    try {
      const res = await apiClient.get(
        `/decisions/unified/?source=afm&afm=${afm}&view=date_range`
      );
      setEntityDateRange(res.data);

      if (res.data.has_data) {
        const dateUtils = createDynamicDateRangeUtils(res.data);
        setDynamicDateUtils(dateUtils);
        const defaultRange = dateUtils.getProgressiveDefaultRange(
          res.data.activity_chart?.data
        );
        setMonthRange(defaultRange);
        setTimeRange({
          startDate: dateUtils.indexToDateString(defaultRange.startIndex),
          endDate: dateUtils.indexToDateString(defaultRange.endIndex, true)
        });
      }
    } catch (err) {
      console.error('Failed to fetch date range:', err);
    } finally {
      setDateRangeLoading(false);
    }
  }, [afm]);

  // Fetch statistics - non-blocking, fire-and-forget
  const fetchStatistics = useCallback(async () => {
    if (!timeRange) return;
    setStatisticsLoading(true);
    setStatisticsError(null);
    try {
      const res = await apiClient.get(
        `/decisions/unified/?source=afm&afm=${afm}&view=statistics&start_date=${timeRange.startDate}&end_date=${timeRange.endDate}`,
        { timeout: 60000 }
      );
      // compute_statistics shape: { period, summary: { decisions, financial, organizations_count, ... }, entity }
      const data = res.data;
      const summary = data.summary || {};
      const decSummary = summary.decisions || {};
      setStatistics({
        total_decisions: decSummary.total_count,
        unique_roles: data.unique_roles ?? '-',           // not available in compute_statistics
        total_amount: decSummary.total_amount,
        unique_organizations: summary.organizations_count,
        decisions_with_amounts: decSummary.total_count,    // approximate
        most_frequent_organization: null,                  // not available in compute_statistics
      });
    } catch (err) {
      setStatisticsError(err.message);
    } finally {
      setStatisticsLoading(false);
    }
  }, [afm, timeRange]);

  // Initial load: fetch entity metadata + date range in parallel
  useEffect(() => {
    const loadInitialData = async () => {
      setError(null);

      try {
        await Promise.all([
          fetchEntityMetadata(),
          fetchDateRange()
        ]);
      } catch (err) {
        setError(err.message);
      }
    };

    loadInitialData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [afm]);

  // Load statistics when requested by user and timeRange/filters change
  useEffect(() => {
    if (!timeRange || !statsRequested) return;
    fetchStatistics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeRange, sortBy, directAssignmentsOnly, debouncedSearchQuery, selectedDecisionTypes, amountFilters, statsRequested]);

  useEffect(() => {
    let cancelled = false;
    apiClient.get(`/companies/afm/${afm}/`)
      .then(res => { if (!cancelled) setCompanyInfo(res.data); })
      .catch(() => { /* feature may be disabled or entity has no company record */ });
    return () => { cancelled = true; };
  }, [afm]);

  const { fetchContent: handleViewDocumentContent } = useDocumentContent();

  const handleRequestGemiFetch = async () => {
    setGemiFetchStatus('loading');
    try {
      const response = await apiClient.post(`/entity/afm/${afm}/request-fetch/`);
      const status = response.data?.status;
      if (status === 'queued') {
        setGemiFetchStatus('queued');
      } else if (status === 'already_queued') {
        setGemiFetchStatus('already_queued');
      } else if (status === 'already_fetched') {
        setGemiFetchStatus('already_fetched');
      } else {
        setGemiFetchStatus('error');
      }
    } catch (err) {
      if (err.response?.status === 429) {
        setGemiFetchStatus('rate_limited');
      } else if (err.response?.status === 503) {
        // Feature flag flipped server-side between page load and click
        setGemiFetchStatus('error');
      } else if (err.response?.status === 401) {
        // Use the same auth modal pattern as the rest of the app
        setGemiFetchStatus(null);
        window.dispatchEvent(new CustomEvent('authRequired', {
          detail: {
            supertitle: t('afmEntityDetail.requestGemiFetchAuthSupertitle'),
            message: t('afmEntityDetail.requestGemiFetchAuthMessage'),
          }
        }));
      } else {
        setGemiFetchStatus('error');
      }
    }
  };

  // Month range slider handler
  const handleMonthRangeChange = (startIndex, endIndex) => {
    if (!dynamicDateUtils) return;

    const startDate = dynamicDateUtils.indexToDateString(startIndex);
    const endDate = dynamicDateUtils.indexToDateString(endIndex, true);

    setMonthRange({ startIndex, endIndex });
    setTimeRange({
      startDate,
      endDate
    });
  };

  // Build statistics cards for StatisticsGrid
  const statCards = statistics ? [
    {
      title: t('afmEntityDetail.totalDecisions'),
      value: statistics.total_decisions?.toLocaleString(),
      subtitle: t('afmEntityDetail.acrossRoles', { count: statistics.unique_roles }),
    },
    {
      title: t('afmEntityDetail.totalAmount'),
      value: formatAmount(statistics.total_amount),
      subtitle: statistics.decisions_with_amounts ? (
        <span>{t('afmEntityDetail.decisionsWithAmounts', { count: statistics.decisions_with_amounts })}</span>
      ) : undefined,
    },
    {
      title: t('afmEntityDetail.organizationsWorkedWith'),
      value: statistics.unique_organizations?.toLocaleString(),
      subtitle: statistics.most_frequent_organization ? (
        <button
          className="most-frequent-org clickable-entity"
          onClick={() => navigate(`/entity/organization/${statistics.most_frequent_organization.uid}`)}
          title={t('afmEntityDetail.viewMostFrequentOrg')}
        >
          {t('afmEntityDetail.mostFrequent')}: {statistics.most_frequent_organization.label}
        </button>
      ) : undefined,
    },
    {
      title: t('afmEntityDetail.activityPeriod'),
      value: timeRange ? `${Math.ceil((new Date(timeRange.endDate) - new Date(timeRange.startDate)) / 86400000)} ${t('common.days')}` : '-',
      subtitle: timeRange ? `${timeRange.startDate} — ${timeRange.endDate}` : undefined,
    },
  ] : null;

  if (dateRangeLoading || (loading && !entity)) {
    return (
      <div className="loading-container">
        <h2>{t('afmEntityDetail.loadingEntity', { afm })}</h2>
        <div className="spinner"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-container">
        <h2>{t('afmEntityDetail.errorLoadingEntity')}</h2>
        <p>{error}</p>
        <button onClick={() => navigate(-1)} className="back-button">
          {t('common.goBack')}
        </button>
      </div>
    );
  }

  if (!entity) {
    return (
      <div className="not-found-container">
        <h2>{t('afmEntityDetail.entityNotFound')}</h2>
        <p>{t('afmEntityDetail.entityNotFoundMessage', { afm })}</p>
        <button onClick={() => navigate(-1)} className="back-button">
          {t('common.goBack')}
        </button>
      </div>
    );
  }

  // No data available for this entity
  if (entityDateRange && !entityDateRange.has_data) {
    return (
      <div className="not-found-container">
        <h2>{t('entityDetail.noDataAvailable')}</h2>
        <p>{entityDateRange.message || t('afmEntityDetail.noDataForAfm', { afm })}</p>
      </div>
    );
  }

  return (
    <div className="afm-entity-detail-page">
      {/* Entity name rendered into the fixed top bar */}
      <TopBarSlot>
        <div className="entity-header-topbar">
          <span className="entity-title-topbar">
            {entity.name || t('afmEntityDetail.unknownEntity')}
          </span>
        </div>
      </TopBarSlot>

      {/* Header Section */}
      <div className="entity-header">
        <div className="breadcrumb">
          <button onClick={() => navigate(-1)} className="breadcrumb-link">
            {t('navigation.back')}
          </button>
          <span className="breadcrumb-separator">•</span>
          <span>{t('afmEntityDetail.entityDetails')}</span>
        </div>

        <div className="entity-metadata">
          <span className="afm-badge">AFM: {entity.afm}</span>
          <span className="appearances-badge">
            {t('afmEntityDetail.totalAppearances', { count: entity.total_appearances })}
          </span>
        </div>

        <div className="entity-activity-period">
          <span className="activity-label">{t('afmEntityDetail.activeFrom')}</span>
          <span className="activity-date">
            {new Date(entity.first_seen).toLocaleDateString('en-GB', {
              day: '2-digit',
              month: '2-digit',
              year: 'numeric'
            })}
          </span>
          <span className="activity-separator">—</span>
          <span className="activity-date">
            {new Date(entity.last_seen).toLocaleDateString('en-GB', {
              day: '2-digit',
              month: '2-digit',
              year: 'numeric'
            })}
          </span>
        </div>
      </div>

      {/* Date range slider - Collapsible */}
      {dynamicDateUtils && monthRange && (
        <TimeRangeSection
          dynamicDateUtils={dynamicDateUtils}
          monthRange={monthRange}
          onMonthRangeChange={handleMonthRangeChange}
          dateRange={entityDateRange.date_range}
          activityData={entityDateRange?.activity_chart}
        />
      )}

      {/* Unified GEMI Section */}
      <GemiSection
        companyInfo={companyInfo}
        entity={entity}
        gemiFetchStatus={gemiFetchStatus}
        onRequestFetch={handleRequestGemiFetch}
      />

      {/* Statistics Grid - triggered manually by user */}
      {!statsRequested ? (
        <div className="statistics-manual-trigger" style={{ marginBottom: '1rem' }}>
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
          loading={statisticsLoading && !statistics}
          error={statisticsError}
          cards={statCards}
          onRetry={fetchStatistics}
        />
      )}

      {/* Top Organizations - respects timeRange */}
      {entity && (
        <TopCounterparts
          type="entity"
          id={entity.afm}
          dateRange={{
            start_date: timeRange?.startDate || entity.first_seen,
            end_date: timeRange?.endDate || entity.last_seen
          }}
          limit={5}
          onCounterpartClick={(counterpart) => {
            const orgUid = counterpart.decision__organization__uid;
            const sd = timeRange?.startDate || entity.first_seen;
            const ed = timeRange?.endDate || entity.last_seen;
            navigate(`/relationship/entity/${entity.afm}/org/${orgUid}?start_date=${sd}&end_date=${ed}`);
          }}
        />
      )}

      {/* Decisions Section */}
        <DecisionsToolbar
          title={t('afmEntityDetail.relatedDecisions')}
          totalCount={pagination?.total_items}
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
          onApplyFilters={(updates) => updateUrl(updates)}
          decisionTypes={availableDecisionTypes}
          selectedTypes={selectedDecisionTypes}
          onTypeToggle={toggleType}
          typesLoading={decisionTypesLoading}
          pagination={pagination}
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
            emptyMessage={t('afmEntityDetail.noDecisions')}
            emptyFilterMessage={t('afmEntityDetail.noDecisionsWithFilters')}
            infiniteScroll={true}
            getDecisionKey={(d) => d.id}
          />
        </DecisionsToolbar>
    </div>
  );
};

export default AFMEntityDetailPage;
