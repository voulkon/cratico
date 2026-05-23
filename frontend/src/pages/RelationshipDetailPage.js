import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import relationshipsApi from '../api/relationshipsApi';
import useUrlFilters from '../hooks/useUrlFilters';
import DecisionCard from '../components/DecisionCard';
import SortControl from '../components/SortControl';
import apiClient from '../api/client';
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
  const [decisions, setDecisions] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [statistics, setStatistics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  // Date range from URL or default to all time
  const startDate = searchParams.get('start_date') || '';
  const endDate = searchParams.get('end_date') || '';

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

  const [availableDecisionTypes, setAvailableDecisionTypes] = useState([]);
  const [showFilters, setShowFilters] = useState(false);

  // Fetch relationship data
  useEffect(() => {
    const fetchRelationshipData = async () => {
      try {
        setLoading(true);
        setError(null);

        const params = {
          start_date: startDate,
          end_date: endDate,
          sort_by: sortBy,
          page: 1,
          page_size: 20
        };

        // Add filters
        if (searchQuery) params.search_query = searchQuery;
        if (selectedTypes.length > 0) params.decision_types = selectedTypes.join(',');
        if (amountFilters.minAmount) params.min_amount = amountFilters.minAmount;
        if (amountFilters.maxAmount) params.max_amount = amountFilters.maxAmount;
        if (directAssignmentsOnly) params.direct_assignments_only = true;

        const data = await relationshipsApi.getRelationshipDecisions(afm, orgUid, params);

        setDecisions(data.results);
        setPagination(data.pagination);

        // Extract entity and organization info from first decision
        if (data.results.length > 0) {
          const firstDecision = data.results[0];
          setOrganization(firstDecision.organization);
          setEntity(firstDecision.main_recipient || { afm, name: 'Unknown Entity' });

          // Calculate statistics
          const totalAmount = data.results.reduce((sum, d) => sum + (d.entity_amount || 0), 0);
          setStatistics({
            total_decisions: data.pagination.total_count,
            total_amount: totalAmount,
            date_range: { start: startDate, end: endDate }
          });
        }

        // Get available decision types for filtering
        const uniqueTypes = [...new Set(data.results
          .map(d => d.decision_type)
          .filter(Boolean)
        )];
        setAvailableDecisionTypes(uniqueTypes);

      } catch (err) {
        console.error('Error fetching relationship data:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    if (afm && orgUid) {
      fetchRelationshipData();
    }
  }, [afm, orgUid, startDate, endDate, sortBy, searchQuery, selectedTypes, amountFilters, directAssignmentsOnly]);

  const handleLoadMore = async () => {
    if (!pagination?.has_next || loadingMore) return;

    try {
      setLoadingMore(true);
      const params = {
        start_date: startDate,
        end_date: endDate,
        sort_by: sortBy,
        page: pagination.current_page + 1,
        page_size: 20
      };

      if (searchQuery) params.search_query = searchQuery;
      if (selectedTypes.length > 0) params.decision_types = selectedTypes.join(',');
      if (amountFilters.minAmount) params.min_amount = amountFilters.minAmount;
      if (amountFilters.maxAmount) params.max_amount = amountFilters.maxAmount;
      if (directAssignmentsOnly) params.direct_assignments_only = true;

      const data = await relationshipsApi.getRelationshipDecisions(afm, orgUid, params);
      setDecisions(prev => [...prev, ...data.results]);
      setPagination(data.pagination);
    } catch (err) {
      console.error('Error loading more decisions:', err);
    } finally {
      setLoadingMore(false);
    }
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

  const formatAmount = (amount) => {
    if (!amount || amount === 0) return t('common.noAmount');
    return `€${amount.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`;
  };

  if (loading && !entity) {
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

      {/* Statistics Section */}
      {statistics && (
        <div className="statistics-grid">
          <div className="stat-card">
            <h3>{t('relationship.totalDecisions')}</h3>
            <div className="stat-value">{statistics.total_decisions.toLocaleString()}</div>
          </div>

          <div className="stat-card">
            <h3>{t('relationship.totalAmount')}</h3>
            <div className="stat-value">{formatAmount(statistics.total_amount)}</div>
          </div>

          {startDate && endDate && (
            <div className="stat-card">
              <h3>{t('relationship.dateRange')}</h3>
              <div className="stat-value date-range">
                {new Date(startDate).toLocaleDateString()} - {new Date(endDate).toLocaleDateString()}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Decisions Section */}
      <div className="decisions-section">
        <div className="decisions-header">
          <h3 className="decisions-title">
            {t('relationship.decisions')} ({pagination?.total_count || 0})
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
            <SortControl sortBy={sortBy} onSortChange={setSortBy} />
            <button
              className="filter-toggle-button"
              onClick={() => setShowFilters(!showFilters)}
            >
              {t('common.filters')} {showFilters ? '▲' : '▼'}
              {activeFiltersCount > 0 && ` (${activeFiltersCount})`}
            </button>
          </div>
        </div>

        {/* Filters Panel */}
        {showFilters && (
          <div className="filters-panel">
            {/* Search */}
            <div className="filter-group">
              <label>{t('filters.search')}</label>
              <input
                type="text"
                placeholder={t('filters.searchPlaceholder')}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="search-input"
              />
            </div>

            {/* Decision Types */}
            {availableDecisionTypes.length > 0 && (
              <div className="filter-group">
                <label>{t('filters.decisionTypes')}</label>
                <div className="checkbox-group">
                  {availableDecisionTypes.map(type => (
                    <label key={type.uid} className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={selectedTypes.includes(type.uid)}
                        onChange={() => toggleType(type.uid)}
                      />
                      <span>{type.label}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}

            {/* Amount Range */}
            <div className="filter-group">
              <label>{t('filters.amountRange')}</label>
              <div className="amount-inputs">
                <input
                  type="number"
                  placeholder={t('filters.minAmount')}
                  value={amountFilters.minAmount}
                  onChange={(e) => setAmountFilters({ ...amountFilters, minAmount: e.target.value })}
                />
                <span>—</span>
                <input
                  type="number"
                  placeholder={t('filters.maxAmount')}
                  value={amountFilters.maxAmount}
                  onChange={(e) => setAmountFilters({ ...amountFilters, maxAmount: e.target.value })}
                />
              </div>
            </div>

            {activeFiltersCount > 0 && (
              <button onClick={clearAllFilters} className="clear-filters-button">
                {t('common.clearFilters')}
              </button>
            )}
          </div>
        )}

        {/* Decisions List */}
        {loading ? (
          <div className="loading-text">{t('common.loading')}</div>
        ) : decisions.length === 0 ? (
          <div className="no-decisions-message">
            {activeFiltersCount > 0
              ? t('relationship.noDecisionsWithFilters')
              : t('relationship.noDecisions')
            }
          </div>
        ) : (
          <>
            <div className="decisions-list">
              {decisions.map((decision, index) => (
                <DecisionCard
                  key={decision.id}
                  decision={decision}
                  formatAmount={formatAmount}
                  index={index}
                  isLastItem={index === decisions.length - 1}
                  onViewDocumentContent={handleViewDocumentContent}
                />
              ))}
            </div>

            {pagination?.has_next && (
              <div className="load-more-container">
                <button
                  onClick={handleLoadMore}
                  disabled={loadingMore}
                  className={`load-more-button ${loadingMore ? 'loading' : ''}`}
                >
                  {loadingMore ? t('common.loading') : t('common.loadMore')}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default RelationshipDetailPage;
