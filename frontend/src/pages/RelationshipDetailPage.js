import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import useUrlFilters from '../hooks/useUrlFilters';
import useDecisionsList from '../hooks/useDecisionsList';
import useDecisionTypes from '../hooks/useDecisionTypes';
import DecisionList from '../components/DecisionList';
import DecisionsToolbar from '../components/DecisionsToolbar';
import TimeRangeSection from '../components/TimeRangeSection';
import StatisticsGrid from '../components/StatisticsGrid';
import apiClient from '../api/client';
import { createDynamicDateRangeUtils } from '../utils/dateUtils';
import { formatAmount } from '../utils/format';
import './RelationshipDetailPage.css';

/**
 * Page showing the relationship between a specific AFM Entity and Organization
 * Displays all decisions linking them together
 */
const RelationshipDetailPage = () => {
  const { afm, orgUid } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();

  const [entity, setEntity] = useState(null);
  const [organization, setOrganization] = useState(null);

  // Build a compact tab title: truncate both names so they fit on the browser tab
  const truncate = (s, max = 15) => (s && s.length > max ? s.slice(0, max) + '…' : s);
  const entityLabel = truncate(entity?.name) || `AFM ${afm}`;
  const orgLabel = truncate(organization?.label) || orgUid;
  useDocumentTitle(`${entityLabel} × ${orgLabel}`);
  const [statistics, setStatistics] = useState(null);
  const [statisticsLoading, setStatisticsLoading] = useState(false);
  const [statisticsError, setStatisticsError] = useState(null);
  const [statsRequested, setStatsRequested] = useState(false);
  const [error, setError] = useState(null);

  // Date range state
  const [entityDateRange, setEntityDateRange] = useState(null);
  const [dateRangeLoading, setDateRangeLoading] = useState(true);
  const [dynamicDateUtils, setDynamicDateUtils] = useState(null);
  const [timeRange, setTimeRange] = useState(null);
  const [monthRange, setMonthRange] = useState(null);

  // Use URL filters hook
  const {
    sortBy,
    searchQuery,
    selectedTypes,
    amountFilters,
    directAssignmentsOnly,
    activeFiltersCount,
    setSortBy,
    setSearchQuery,
    toggleType,
    setAmountFilters,
    setDirectAssignmentsOnly,
    clearAllFilters
  } = useUrlFilters({ sortBy: 'entity_amount_desc' });

  // Decision types are now owned by the useDecisionTypes hook below.

  // ── Fetch date range on mount ──────────────────────────────────────────
  const fetchEntityDateRange = useCallback(async () => {
    try {
      setDateRangeLoading(true);
      const response = await apiClient.get(
        `/relationship/entity/${afm}/org/${orgUid}/date-range/`
      );
      setEntityDateRange(response.data);

      if (response.data.has_data) {
        const dateUtils = createDynamicDateRangeUtils(response.data);
        setDynamicDateUtils(dateUtils);

        // Seed from URL params if present, otherwise use default range
        const urlStart = searchParams.get('start_date');
        const urlEnd = searchParams.get('end_date');

        if (urlStart && urlEnd) {
          const rawStartIdx = dateUtils.dateToIndex(new Date(urlStart));
          const rawEndIdx = dateUtils.dateToIndex(new Date(urlEnd));
          // Clamp to valid range to prevent slider handles overflowing the track
          const maxIdx = dateUtils.totalMonths - 1;
          const startIdx = Math.max(0, Math.min(maxIdx, rawStartIdx));
          const endIdx = Math.max(0, Math.min(maxIdx, rawEndIdx));
          setMonthRange({
            startIndex: Math.min(startIdx, endIdx),
            endIndex: Math.max(startIdx, endIdx),
          });
          setTimeRange({ startDate: urlStart, endDate: urlEnd });
        } else {
          const defaultRange = dateUtils.getProgressiveDefaultRange(
            response.data.activity_chart?.data
          );
          setMonthRange(defaultRange);
          setTimeRange({
            startDate: dateUtils.indexToDateString(defaultRange.startIndex),
            endDate: dateUtils.indexToDateString(defaultRange.endIndex, true),
          });
        }
      }
    } catch (err) {
      console.error('Failed to fetch relationship date range:', err);
      setError(err.message);
    } finally {
      setDateRangeLoading(false);
    }
  }, [afm, orgUid, searchParams]);

  // Initial load
  useEffect(() => {
    if (afm && orgUid) {
      fetchEntityDateRange();
    }
  }, [afm, orgUid]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Decision types via shared hook (scans entire relationship, not just loaded batch) ──
  const { decisionTypes: availableDecisionTypes, loading: decisionTypesLoading } =
    useDecisionTypes({
      endpoint: `/relationship/entity/${afm}/org/${orgUid}/decision-types/`,
      dateRange: timeRange,
    });

  // ── Async statistics fetch ─────────────────────────────────────────────────
  const fetchStatistics = useCallback(async () => {
    if (!timeRange) return;

    setStatisticsLoading(true);
    setStatisticsError(null);

    try {
      const params = new URLSearchParams({
        start_date: timeRange.startDate,
        end_date: timeRange.endDate,
      });
      const response = await apiClient.get(
        `/relationship/entity/${afm}/org/${orgUid}/statistics/?${params}`,
        { timeout: 60000 }
      );
      setStatistics(response.data);
    } catch (err) {
      console.error('Failed to fetch relationship statistics:', err);
      setStatisticsError(t('statistics.loadError'));
    } finally {
      setStatisticsLoading(false);
    }
  }, [afm, orgUid, timeRange, t]);

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
      source: 'relationship',
      view: 'decisions',
      afm,
      org_uid: orgUid,
      start_date: timeRange?.startDate,
      end_date: timeRange?.endDate,
      sort_by: sortBy,
      ...(searchQuery && { q: searchQuery }),
      ...(selectedTypes.length > 0 && { decision_types: selectedTypes.join(',') }),
      ...(amountFilters.minAmount && { min_amount: amountFilters.minAmount }),
      ...(amountFilters.maxAmount && { max_amount: amountFilters.maxAmount }),
      ...(directAssignmentsOnly && { direct_assignments_only: 'true' }),
    },
    enabled: !!timeRange,
  });

  // Extract entity & organization info from first decision (reactive)
  useEffect(() => {
    if (decisions.length > 0 && !entity) {
      const firstDecision = decisions[0];
      setOrganization(firstDecision.organization);
      setEntity(firstDecision.main_recipient || { afm, name: 'Unknown Entity' });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [decisions]);

  // Statistics load on demand when user clicks "Load statistics"
  useEffect(() => {
    if (!timeRange || !statsRequested) return;
    fetchStatistics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeRange, statsRequested]);

  // ── Slider handlers ────────────────────────────────────────────────────────
  const handleMonthRangeChange = (startIndex, endIndex) => {
    if (!dynamicDateUtils) return;

    setMonthRange({ startIndex, endIndex });
    setTimeRange({
      startDate: dynamicDateUtils.indexToDateString(startIndex),
      endDate: dynamicDateUtils.indexToDateString(endIndex, true),
    });
  };

  const handleViewDocumentContent = async (decisionId) => {
    try {
      const response = await apiClient.get(`/decision/${decisionId}/content/`);
      return response.data;
    } catch (error) {
      console.error('Error fetching document content:', error);
      throw error;
    }
  };

  // ── Sync timeRange to URL params for shareable links ─────────────────────
  const [, setSearchParams] = useSearchParams();

  useEffect(() => {
    if (timeRange) {
      setSearchParams({
        start_date: timeRange.startDate,
        end_date: timeRange.endDate,
      }, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeRange]);

  if ((loading || dateRangeLoading) && !entity) {
    return (
      <div className="relationship-page loading-container">
        <h2>{t('relationship.loading')}</h2>
        <div className="spinner"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="relationship-page error-container">
        <h2>{t('relationship.error')}</h2>
        <p>{error}</p>
        <button onClick={() => navigate(-1)} className="back-button">
          {t('common.goBack')}
        </button>
      </div>
    );
  }

  if (!entity || !organization) {
    return (
      <div className="relationship-page not-found-container">
        <h2>{t('relationship.noData')}</h2>
        <p>{t('relationship.noDataMessage')}</p>
        <button onClick={() => navigate(-1)} className="back-button">
          {t('common.goBack')}
        </button>
      </div>
    );
  }

  return (
    <div className="relationship-detail-page">
      {/* Breadcrumb */}
      <div className="breadcrumb">
        <button onClick={() => navigate(-1)} className="breadcrumb-link">
          {t('navigation.back')}
        </button>
        <span className="breadcrumb-separator">•</span>
        <span>{t('relationship.title')}</span>
      </div>

      {/* Header Section */}
      <div className="relationship-header">
        <h1 className="relationship-title">{t('relationship.pageTitle')}</h1>

        <div className="relationship-entities">
          <button
            className="entity-card clickable"
            onClick={() => navigate(`/entity/afm/${afm}`)}
          >
            <span className="entity-label">{t('relationship.entity')}</span>
            <span className="entity-name">{entity.name}</span>
            <span className="entity-id">AFM: {afm}</span>
          </button>

          <div className="relationship-connector">
            <div className="connector-line"></div>
            <span className="connector-icon">⇄</span>
            <div className="connector-line"></div>
          </div>

          <button
            className="entity-card clickable"
            onClick={() => navigate(`/entity/organization/${orgUid}`)}
          >
            <span className="entity-label">{t('relationship.organization')}</span>
            <span className="entity-name">{organization.label}</span>
            <span className="entity-id">UID: {orgUid}</span>
          </button>
        </div>
      </div>

      {/* Time Range Slider */}
      {dynamicDateUtils && monthRange && (
        <TimeRangeSection
          dynamicDateUtils={dynamicDateUtils}
          monthRange={monthRange}
          onMonthRangeChange={handleMonthRangeChange}
          dateRange={entityDateRange?.date_range}
          activityData={entityDateRange?.activity_chart}
        />
      )}

      {/* Statistics Section - triggered manually by user */}
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
          columns={3}
          cards={
            statistics
              ? [
                  {
                    title: t('relationship.totalDecisions'),
                    value: statistics.total_decisions?.toLocaleString() || '0',
                  },
                  {
                    title: t('relationship.totalAmount'),
                    value: formatAmount(statistics.total_amount),
                  },
                  {
                    title: t('statistics.averageAmount'),
                    value: formatAmount(statistics.avg_amount),
                    subtitle: statistics.decisions_with_amounts
                      ? `${statistics.decisions_with_amounts} ${t('relationship.withAmounts')}`
                      : '',
                  },
                ]
              : null
          }
          onRetry={fetchStatistics}
        />
      )}

      {/* Decisions Section */}
        <DecisionsToolbar
          title={t('relationship.decisions')}
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
          selectedTypes={selectedTypes}
          onTypeToggle={toggleType}
          typesLoading={decisionTypesLoading}
          pagination={pagination}
        >
          <DecisionList
            decisions={decisions}
            loading={loading}
            loadingMore={loadingMore}
            pagination={pagination}
            hasSearchQuery={activeFiltersCount > 0}
            formatAmount={formatAmount}
            onViewDocumentContent={handleViewDocumentContent}
            onLoadMore={loadMore}
            emptyMessage={t('relationship.noDecisions')}
            emptyFilterMessage={t('relationship.noDecisionsWithFilters')}
            infiniteScroll={true}
            getDecisionKey={(d) => d.id}
          />
        </DecisionsToolbar>
    </div>
  );
};

export default RelationshipDetailPage;
