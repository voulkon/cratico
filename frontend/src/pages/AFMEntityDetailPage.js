import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Filter } from 'lucide-react';
import apiClient from '../api/client';
import { useTranslation } from '../contexts/TranslationContext';
import useUrlFilters from '../hooks/useUrlFilters';
import DecisionCard from '../components/DecisionCard';
import SortControl from '../components/SortControl';
import TopCounterparts from '../components/TopCounterparts';
import GemiSection from '../components/GemiSection';
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
  const [showRoleFilter, setShowRoleFilter] = useState(false);
  const [companyInfo, setCompanyInfo] = useState(null);
  const [gemiFetchStatus, setGemiFetchStatus] = useState(null); // null | 'loading' | 'queued' | 'already_queued' | 'already_fetched' | 'rate_limited' | 'error'

  // Use URL filters hook - replaces all the manual URL state management
  const {
    sortBy,
    selectedRoles,
    directAssignmentsOnly,
    activeFiltersCount,
    setSortBy,
    toggleRole,
    setDirectAssignmentsOnly,
    clearAllFilters
  } = useUrlFilters({ sortBy: 'amount_desc' });

  const fetchEntityData = useCallback(async (loadMore = false) => {
    try {
      if (!loadMore) {
        setLoading(true);
      } else {
        setLoadingMore(true);
      }

      // Fetch entity details
      const entityResponse = await apiClient.get(`/entity/afm/${afm}/`);
      setEntity(entityResponse.data.entity);
      setStatistics(entityResponse.data.statistics);
      setAvailableRoles(entityResponse.data.available_roles);

      // Fetch decisions with current filters
      const decisionsParams = new URLSearchParams({
        sort: sortBy,
        page: loadMore ? (pagination?.current_page + 1 || 2) : 1,
        ...(selectedRoles.length > 0 && { roles: selectedRoles.join(',') }),
        ...(directAssignmentsOnly && { direct_assignments_only: 'true' })
      });

      const decisionsResponse = await apiClient.get(`/entity/afm/${afm}/decisions/?${decisionsParams}`);

      if (loadMore) {
        setDecisions(prev => [...prev, ...decisionsResponse.data.results]);
      } else {
        setDecisions(decisionsResponse.data.results);
      }

      setPagination(decisionsResponse.data.pagination);

    } catch (err) {
      console.error('Error fetching AFM entity data:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [afm, sortBy, selectedRoles, directAssignmentsOnly, pagination]);

  // Fetch data when filters change - omitting fetchEntityData to avoid infinite loop
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    fetchEntityData();
  }, [afm, sortBy, selectedRoles, directAssignmentsOnly]);

  useEffect(() => {
    let cancelled = false;
    apiClient.get(`/companies/afm/${afm}/`)
      .then(res => { if (!cancelled) setCompanyInfo(res.data); })
      .catch(() => { /* feature may be disabled or entity has no company record */ });
    return () => { cancelled = true; };
  }, [afm]);

  const handleLoadMore = () => {
    if (pagination?.has_next && !loadingMore) {
      fetchEntityData(true);
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

  const formatAmount = (amount) => {
    if (!amount || amount === 0) return t('common.noAmount');
    return `€${amount.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`;
  };

  if (loading && !entity) {
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

      {/* Statistics Grid */}
      {statistics && (
        <div className="statistics-grid">
          <div className="stat-card">
            <h3>{t('afmEntityDetail.totalDecisions')}</h3>
            <div className="stat-value">{statistics.total_decisions?.toLocaleString()}</div>
            <div className="stat-context">
              {t('afmEntityDetail.acrossRoles', { count: statistics.unique_roles })}
            </div>
          </div>

          <div className="stat-card">
            <h3>{t('afmEntityDetail.totalAmount')}</h3>
            <div className="stat-value">
              {statistics.total_amount ? formatAmount(statistics.total_amount) : t('common.noAmount')}
            </div>
            <div className="stat-context">
              {statistics.decisions_with_amounts && (
                <span>
                  {t('afmEntityDetail.decisionsWithAmounts', { count: statistics.decisions_with_amounts })}
                </span>
              )}
            </div>
          </div>

          <div className="stat-card">
            <h3>{t('afmEntityDetail.organizationsWorkedWith')}</h3>
            <div className="stat-value">{statistics.unique_organizations?.toLocaleString()}</div>
            <div className="stat-context">
              {statistics.most_frequent_organization && (
                <button
                  className="most-frequent-org clickable-entity"
                  onClick={() => navigate(`/entity/organization/${statistics.most_frequent_organization.uid}`)}
                  title={t('afmEntityDetail.viewMostFrequentOrg')}
                >
                  {t('afmEntityDetail.mostFrequent')}: {statistics.most_frequent_organization.label}
                </button>
              )}
            </div>
          </div>

          <div className="stat-card">
            <h3>{t('afmEntityDetail.activityPeriod')}</h3>
            <div className="stat-value">
              {Math.ceil((new Date(entity.last_seen) - new Date(entity.first_seen)) / (1000 * 60 * 60 * 24))} {t('common.days')}
            </div>
            <div className="stat-context">
              {statistics.avg_decisions_per_month && (
                <span>
                  {t('afmEntityDetail.avgPerMonth', { count: statistics.avg_decisions_per_month.toFixed(1) })}
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Top Organizations - Shows top organizations this entity worked with */}
      {entity && (
        <TopCounterparts
          type="entity"
          id={entity.afm}
          dateRange={{
            start_date: entity.first_seen,
            end_date: entity.last_seen
          }}
          limit={5}
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
        <div className="filters-section">
          <div
            className="filters-header clickable"
            onClick={() => setShowRoleFilter(!showRoleFilter)}
          >
            <div className="filter-toggle-content">
              <Filter size={18} />
              <span>{t('afmEntityDetail.filterByRole')}</span>
              <span className="toggle-arrow">{showRoleFilter ? '▲' : '▼'}</span>
            </div>

            {activeFiltersCount > 0 && (
              <button
                className="clear-filters-button"
                onClick={(e) => {
                  e.stopPropagation();
                  clearAllFilters();
                }}
              >
                {t('common.clearFilters')} ({activeFiltersCount})
              </button>
            )}
          </div>

          {showRoleFilter && (
            <div className="filters-panel">
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
            </div>
          )}
        </div>

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
        {loading && decisions.length === 0 ? (
          <div className="loading-text">{t('common.loading')}</div>
        ) : (
          <>
            {decisions.length === 0 ? (
              <div className="no-decisions-message">
                {selectedRoles.length > 0
                  ? t('afmEntityDetail.noDecisionsWithFilters')
                  : t('afmEntityDetail.noDecisions')
                }
              </div>
            ) : (
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
            )}

            {/* Load More Button */}
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

            {loadingMore && (
              <div className="loading-more-container">
                <div className="loading-more-text">{t('common.loadingMore')}</div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default AFMEntityDetailPage;
