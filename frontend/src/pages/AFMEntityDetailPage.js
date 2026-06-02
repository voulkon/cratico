import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import apiClient from '../api/client';
import { useTranslation } from '../contexts/TranslationContext';
import useUrlFilters from '../hooks/useUrlFilters';
import useDocumentContent from '../hooks/useDocumentContent';
import useInfiniteScroll from '../hooks/useInfiniteScroll';
import SortControl from '../components/SortControl';
import TopCounterparts from '../components/TopCounterparts';
import GemiSection from '../components/GemiSection';
import DecisionList from '../components/DecisionList';
import FilterPanel from '../components/FilterPanel';
import StatisticsGrid from '../components/StatisticsGrid';
import SearchInput from '../components/SearchInput';
import DualRangeSlider from '../components/DualRangeSlider';
import { createDynamicDateRangeUtils, formatAmount } from '../utils/dateUtils';
import './AFMEntityDetailPage.css';

const AFMEntityDetailPage = () => {
  const { afm } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [entity, setEntity] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [statistics, setStatistics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pagination, setPagination] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [availableRoles, setAvailableRoles] = useState([]);
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

  // Use URL filters hook - replaces all the manual URL state management
  const {
    sortBy,
    searchQuery,
    selectedRoles,
    directAssignmentsOnly,
    activeFiltersCount,
    setSortBy,
    setSearchQuery,
    toggleRole,
    setDirectAssignmentsOnly,
    clearAllFilters
  } = useUrlFilters({ sortBy: 'amount_desc' });

  // Debounced search query
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState(searchQuery);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearchQuery(searchQuery), 500);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Fetch entity metadata (name, type, roles) - fast, blocks nothing else
  const fetchEntityMetadata = useCallback(async () => {
    try {
      const entityResponse = await apiClient.get(`/entity/afm/${afm}/`);
      setEntity(entityResponse.data.entity);
      setAvailableRoles(entityResponse.data.available_roles);
    } catch (err) {
      console.error('Failed to fetch entity metadata:', err);
      setError(err.response?.data?.error || err.message);
    }
  }, [afm]);

  // Fetch date range for slider - fast, separate from decisions
  const fetchDateRange = useCallback(async () => {
    setDateRangeLoading(true);
    try {
      const res = await apiClient.get(`/entity/afm/${afm}/date-range/`);
      setEntityDateRange(res.data);

      if (res.data.has_data) {
        const dateUtils = createDynamicDateRangeUtils(res.data);
        setDynamicDateUtils(dateUtils);
        const defaultRange = dateUtils.getDefaultRange();
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

  // Fetch decisions with date range, search, and role filters
  const fetchDecisions = useCallback(async (page = 1, append = false) => {
    if (!timeRange) return;

    try {
      if (!append) setLoading(true);
      else setLoadingMore(true);

      const params = new URLSearchParams({
        sort: sortBy,
        page: page.toString(),
        start_date: timeRange.startDate,
        end_date: timeRange.endDate,
        ...(selectedRoles.length > 0 && { roles: selectedRoles.join(',') }),
        ...(directAssignmentsOnly && { direct_assignments_only: 'true' })
      });

      if (debouncedSearchQuery.trim()) {
        params.append('q', debouncedSearchQuery.trim());
      }

      const res = await apiClient.get(`/entity/afm/${afm}/decisions/?${params}`);

      if (append) {
        setDecisions(prev => [...prev, ...res.data.results]);
      } else {
        setDecisions(res.data.results);
      }
      setPagination(res.data.pagination);

    } catch (err) {
      console.error('Error fetching decisions:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      if (!append) setLoading(false);
      else setLoadingMore(false);
    }
  }, [afm, timeRange, sortBy, selectedRoles, directAssignmentsOnly, debouncedSearchQuery]);

  // Fetch statistics - non-blocking, fire-and-forget
  const fetchStatistics = useCallback(async () => {
    if (!timeRange) return;
    setStatisticsLoading(true);
    setStatisticsError(null);
    try {
      const params = new URLSearchParams({
        start_date: timeRange.startDate,
        end_date: timeRange.endDate
      });
      const res = await apiClient.get(`/entity/afm/${afm}/statistics/?${params}`, { timeout: 60000 });
      setStatistics(res.data);
    } catch (err) {
      setStatisticsError(err.message);
    } finally {
      setStatisticsLoading(false);
    }
  }, [afm, timeRange]);

  // Initial load: fetch entity metadata + date range in parallel
  useEffect(() => {
    const loadInitialData = async () => {
      setLoading(true);
      setError(null);

      try {
        await Promise.all([
          fetchEntityMetadata(),
          fetchDateRange()
        ]);
      } catch (err) {
        setError(err.message);
      } finally {
        // loading stays true until decisions arrive via timeRange effect
      }
    };

    loadInitialData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [afm]);

  // Load decisions & statistics when timeRange or filters change
  useEffect(() => {
    if (timeRange) {
      fetchDecisions(1, false);
      fetchStatistics();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeRange, sortBy, selectedRoles, directAssignmentsOnly, debouncedSearchQuery]);

  useEffect(() => {
    let cancelled = false;
    apiClient.get(`/companies/afm/${afm}/`)
      .then(res => { if (!cancelled) setCompanyInfo(res.data); })
      .catch(() => { /* feature may be disabled or entity has no company record */ });
    return () => { cancelled = true; };
  }, [afm]);

  const loadMoreDecisions = useCallback(() => {
    if (pagination?.has_next && !loadingMore) {
      fetchDecisions(pagination.current_page + 1, true);
    }
  }, [pagination, loadingMore, fetchDecisions]);

  const { sentinelRef } = useInfiniteScroll({
    hasMore: pagination?.has_next || false,
    loading,
    loadingMore,
    onLoadMore: loadMoreDecisions,
    enabled: true
  });

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

  const formatSliderValue = useCallback((value) => {
    if (!dynamicDateUtils) return '';
    return dynamicDateUtils.formatMonth(value);
  }, [dynamicDateUtils]);

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
      {/* Header Section */}
      <div className="entity-header">
        <div className="breadcrumb">
          <button onClick={() => navigate(-1)} className="breadcrumb-link">
            {t('navigation.back')}
          </button>
          <span className="breadcrumb-separator">•</span>
          <span>{t('afmEntityDetail.entityDetails')}</span>
        </div>

        <h1 className="entity-title">
          {entity.name || t('afmEntityDetail.unknownEntity')}
        </h1>

        <div className="entity-metadata">
          <span className="afm-badge">AFM: {entity.afm}</span>
          <span className={`entity-type-badge ${entity.entity_type}`}>
            {t(`afmEntityDetail.entityTypes.${entity.entity_type}`)}
          </span>
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

      {/* Search bar - context-aware, filters within this entity */}
      <div className="entity-search-bar">
        <SearchInput
          value={searchQuery}
          onChange={setSearchQuery}
          placeholder={t('search.searchInEntity', { name: entity.name })}
        />
      </div>

      {/* Date range slider - Collapsible */}
      {dynamicDateUtils && monthRange && (
        <details open className="time-range-container collapsible-section">
          <summary className="section-summary">
            <span className="summary-title">{t('exploration.timeRange')}</span>
            <span className="summary-count">
              {t('exploration.availableDataShort', {
                days: entityDateRange.date_range.span_days
              })}
            </span>
            <span className="toggle-icon">▼</span>
          </summary>
          <div className="section-content">
            <DualRangeSlider
              min={0}
              max={dynamicDateUtils.totalMonths - 1}
              startValue={monthRange.startIndex}
              endValue={monthRange.endIndex}
              onChange={handleMonthRangeChange}
              formatValue={formatSliderValue}
              activityData={entityDateRange?.activity_chart}
            />
          </div>
        </details>
      )}

      {/* Statistics Grid - non-blocking loading */}
      <StatisticsGrid
        loading={statisticsLoading && !statistics}
        error={statisticsError}
        cards={statCards}
        onRetry={fetchStatistics}
      />

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

      {/* Unified GEMI Section */}
      <GemiSection
        companyInfo={companyInfo}
        entity={entity}
        gemiFetchStatus={gemiFetchStatus}
        onRequestFetch={handleRequestGemiFetch}
      />

      {/* Role Breakdown */}
      {availableRoles && availableRoles.length > 0 && (
        <div className="roles-section">
          <h3>{t('afmEntityDetail.rolesInDecisions')}</h3>
          <div className="roles-grid">
            {availableRoles.map(role => (
              <div key={role.role} className="role-card">
                <div className="role-header">
                  <span className="role-name">{t(`afmEntityDetail.roles.${role.role}`, role.role)}</span>
                  <span className="role-count">{role.count}</span>
                </div>
                <div className="role-percentage">
                  {((role.count / entity.total_appearances) * 100).toFixed(1)}%
                </div>
                {role.total_amount && (
                  <div className="role-amount">
                    {formatAmount(role.total_amount)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Decisions Section */}
      <div className="decisions-section">
        <div className="decisions-header">
          <h3 className="decisions-title">
            {t('afmEntityDetail.relatedDecisions')} ({pagination?.total_items?.toLocaleString() || decisions.length})
          </h3>

          <div className="controls-container">
            <label className="checkbox-label" style={{ marginRight: '1rem' }}>
              <input
                type="checkbox"
                checked={directAssignmentsOnly}
                onChange={(e) => setDirectAssignmentsOnly(e.target.checked)}
              />
              <span>{t('filters.directAssignmentsOnly', 'Direct Assignments Only')}</span>
            </label>
            <SortControl sortBy={sortBy} onSortChange={setSortBy} options="simple" />
          </div>
        </div>

        {/* Role Filters */}
        <FilterPanel
          activeFiltersCount={activeFiltersCount}
          onClearAll={clearAllFilters}
          filterLabel={t('afmEntityDetail.filterByRole')}
        >
          <div className="role-filters">
            {availableRoles.map(role => (
              <label key={role.role} className="role-filter-checkbox">
                <input
                  type="checkbox"
                  checked={selectedRoles.includes(role.role)}
                  onChange={() => toggleRole(role.role)}
                />
                <span className="checkbox-content">
                  <span className="role-label">
                    {t(`afmEntityDetail.roles.${role.role}`, role.role)}
                  </span>
                  <span className="role-stats">({role.count})</span>
                </span>
              </label>
            ))}
          </div>
        </FilterPanel>

        {/* Active Filters Display */}
        {selectedRoles.length > 0 && (
          <div className="active-filters">
            <span className="filters-label">{t('common.activeFilters')}:</span>
            {selectedRoles.map(role => (
              <span key={role} className="filter-tag">
                {t(`afmEntityDetail.roles.${role}`, role)}
                <button onClick={() => toggleRole(role)}>×</button>
              </span>
            ))}
          </div>
        )}

        {/* Search Results Info */}
        {searchQuery && (
          <div className="search-results-info">
            <span className="search-results-count">
              {t('entityDetail.resultsFound', { count: pagination?.total_items || 0 })}
            </span>
          </div>
        )}

        {/* Results Info */}
        <div className="search-results-info">
          {pagination && (
            <span className="search-results-count">
              {t('common.showingResults', {
                start: ((pagination.current_page - 1) * pagination.page_size) + 1,
                end: Math.min(pagination.current_page * pagination.page_size, pagination.total_items),
                total: pagination.total_items
              })}
            </span>
          )}
        </div>

        {/* Decisions List */}
        <DecisionList
          decisions={decisions}
          loading={loading}
          loadingMore={loadingMore}
          error={null}
          pagination={pagination}
          hasSearchQuery={!!(searchQuery || selectedRoles.length > 0)}
          formatAmount={formatAmount}
          onViewDocumentContent={handleViewDocumentContent}
          onLoadMore={loadMoreDecisions}
          emptyMessage={t('afmEntityDetail.noDecisions')}
          emptyFilterMessage={t('afmEntityDetail.noDecisionsWithFilters')}
          showPaginationInfo={true}
          getDecisionKey={(d) => d.id}
        />

        {/* Infinite scroll sentinel */}
        <div ref={sentinelRef} />
      </div>
    </div>
  );
};

export default AFMEntityDetailPage;
