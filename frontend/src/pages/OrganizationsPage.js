import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { ReactFlowProvider } from 'reactflow';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import organizationApi from '../api/organizationApi';
import apiClient from '../api/client';
import TopCounterparts from '../components/TopCounterparts';
import OrgChartViewer from '../components/org-chart';
import './OrganizationsPage.css';

const OrganizationsPage = () => {
  useDocumentTitle('Organizations');
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const searchTimeoutRef = useRef(null);

  // Get initial orgUid from URL or start empty
  const [orgUid, setOrgUid] = useState(searchParams.get('uid') || null);
  const [inputOrgUid, setInputOrgUid] = useState(searchParams.get('uid') || '');
  const [orgData, setOrgData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Search state
  const [searchResults, setSearchResults] = useState([]);
  const [showSearchResults, setShowSearchResults] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);

  // Date range state for top counterparts
  const [orgDateRange, setOrgDateRange] = useState(null);

  const fetchOrgData = useCallback(async (uid) => {
    if (!uid) return;

    try {
      setLoading(true);
      setError(null);
      const result = await organizationApi.getOrgChart(uid);
      console.log("API response:", result);

      // Extract org_chart_data from the response
      setOrgData(result.org_chart_data);

      // Fetch date range for this organization
      try {
        const dateRangeResponse = await apiClient.get(`/entity/organization/${uid}/date-range/`);
        if (dateRangeResponse.data.has_data) {
          setOrgDateRange({
            start_date: dateRangeResponse.data.start_date,
            end_date: dateRangeResponse.data.end_date
          });
        }
      } catch (dateErr) {
        console.error("Error fetching date range:", dateErr);
        // Non-critical error, continue without date range
      }
    } catch (err) {
      console.error("Error fetching organization data:", err);
      setError(t('organizations.failedToLoad', { uid, message: err.message }));
    } finally {
      setLoading(false);
    }
  }, [t]);

  // Load initial data
  useEffect(() => {
    if (orgUid) {
      fetchOrgData(orgUid);
    }
  }, [orgUid, fetchOrgData]);

  // New search function
  const searchOrganizations = async (query) => {
    if (!query.trim() || query.trim().length < 2) {
      setSearchResults([]);
      setShowSearchResults(false);
      return;
    }

    try {
      setSearchLoading(true);
      const result = await organizationApi.searchOrganizations(query.trim());
      // Handle both organization and signer results
      const allResults = [
        ...(result.results?.organizations || []),
        ...(result.results?.signers || [])
      ];
      setSearchResults(allResults);
      setShowSearchResults(true);
    } catch (err) {
      console.error("Search error:", err);
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  };

  // Debounced search handler
  const handleSearchInput = (e) => {
    const value = e.target.value;
    setInputOrgUid(value);

    // Clear existing timeout
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    // Set new timeout for search
    searchTimeoutRef.current = setTimeout(() => {
      searchOrganizations(value);
    }, 300); // 300ms debounce
  };

  // Handle selecting a search result
  const handleSelectSearchResult = (item) => {
    if (item.type === 'organization') {
      setInputOrgUid(item.id);
      setOrgUid(item.id);
    } else if (item.type === 'signer' && item.organization_id) {
      // For signers, use their organization_id
      setInputOrgUid(item.organization_id);
      setOrgUid(item.organization_id);
    }
    setShowSearchResults(false);
    setSearchResults([]);

    // Update URL
    setSearchParams({ uid: item.type === 'organization' ? item.id : item.organization_id });
  };

  const handleLoadOrganization = () => {
    if (inputOrgUid.trim()) {
      const newOrgUid = inputOrgUid.trim();
      setOrgUid(newOrgUid);
      setShowSearchResults(false);

      // Update URL
      setSearchParams({ uid: newOrgUid });
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      handleLoadOrganization();
    }
  };

  const handleClear = () => {
    setOrgUid(null);
    setInputOrgUid('');
    setOrgData(null);
    setError(null);
    setSearchResults([]);
    setShowSearchResults(false);
    setSearchParams({});
  };

  const handleBackToEntityDetails = () => {
    if (orgUid) {
      navigate(`/entity/organization/${orgUid}`);
    }
  };

  const handleNodeClick = (entityType, entityId) => {
    navigate(`/entity/${entityType}/${entityId}`);
  };

  // Handle popular organization selection
  const handlePopularOrgSelect = (org) => {
    setInputOrgUid(org.uid);
    setOrgUid(org.uid);
    setShowSearchResults(false);
    setSearchParams({ uid: org.uid });
  };

  return (
    <div className="organizations-page">
      <div className="page-header">
        <h1>{t('organizations.title')}</h1>
        <p className="page-description">{t('organizations.description')}</p>
      </div>

      <div className="search-controls">
        <div className="search-section">
          <h3>{t('organizations.searchOrganizations')}</h3>

          <div className="search-input-container">
            <input
              type="text"
              placeholder={t('filters.searchOrganizations')}
              value={inputOrgUid}
              onChange={handleSearchInput}
              onKeyPress={handleKeyPress}
              className="search-input"
            />
            {searchLoading && <div className="search-spinner">⏳</div>}
            {orgUid && (
              <button onClick={handleClear} className="clear-search-button">
                {t('organizations.clear')}
              </button>
            )}
          </div>

          {/* Search Results */}
          {showSearchResults && searchResults.length > 0 && (
            <div className="search-results">
              {searchResults.map((item, index) => (
                <button
                  key={`${item.type}-${item.id}-${index}`}
                  className="search-result-item"
                  onClick={() => handleSelectSearchResult(item)}
                >
                  <div className="search-result-content">
                    <span className="org-label">{item.text}</span>
                    <div className="search-result-meta">
                      <span className={`item-type-badge ${item.type}`}>
                        {item.type === 'organization' ? '🏛️ Οργανισμός' : '👤 Υπογράφων'}
                      </span>
                      <span className="org-uid">ID: {item.id}</span>
                    </div>
                    {item.type === 'signer' && item.organization_name && (
                      <div className="parent-org">
                        📍 {item.organization_name}
                      </div>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Current Organization Info */}
      {orgUid && orgData && (
        <div className="current-org-info">
          <div className="org-info-header">
            <h2>{orgData.name || t('organizations.unknownOrganization')}</h2>
            <div className="org-actions">
              <button onClick={handleBackToEntityDetails} className="back-to-entity-button">
                {t('organizations.backToEntityDetails')}
              </button>
            </div>
          </div>
          <div className="org-metadata">
            <span className="org-uid-badge">UID: {orgUid}</span>
            {orgData.children && (
              <span className="org-stat">
                {t('organizations.totalUnits')}: {orgData.children.filter(c => c.title === 'Unit').length}
              </span>
            )}
            {orgData.children && (
              <span className="org-stat">
                {t('organizations.totalSigners')}: {orgData.children.filter(c => c.title === 'Signer').length}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Top Counterparts - Shows top entities this organization works with */}
      {orgUid && orgDateRange && (
        <TopCounterparts
          type="organization"
          id={orgUid}
          dateRange={orgDateRange}
          limit={5}
          onCounterpartClick={(counterpart) => {
            const afm = counterpart.entity_afm;
            navigate(`/relationship/entity/${afm}/org/${orgUid}?start_date=${orgDateRange.start_date}&end_date=${orgDateRange.end_date}`);
          }}
        />
      )}

      {/* Main Content Area */}
      <div className="main-content">
        {!orgUid ? (
          // Welcome state - no organization selected
          <div className="welcome-state">
            <div className="welcome-content">
              <h2>{t('organizations.welcomeTitle')}</h2>
              <p>{t('organizations.welcomeMessage')}</p>

              <div className="welcome-actions">
                <div className="welcome-option">
                  <h3>{t('organizations.searchTitle')}</h3>
                  <p>{t('organizations.searchDescription')}</p>
                </div>
              </div>

              <div className="popular-organizations">
                <h3>{t('organizations.popularOrganizations')}</h3>
                <div className="popular-org-buttons">
                  <button
                    onClick={() => handlePopularOrgSelect({ uid: '100010899', label: 'ΥΠΟΥΡΓΕΙΟ ΥΓΕΙΑΣ ΚΑΙ ΚΟΙΝΩΝΙΚΩΝ ΑΣΦΑΛΙΣΕΩΝ' })}
                    className="popular-org-button"
                  >
                    🏥 ΥΠΟΥΡΓΕΙΟ ΥΓΕΙΑΣ
                  </button>
                  <button
                    onClick={() => handlePopularOrgSelect({ uid: '15', label: 'ΥΠΟΥΡΓΕΙΟ ΟΙΚΟΝΟΜΙΚΩΝ' })}
                    className="popular-org-button"
                  >
                    💰 ΥΠΟΥΡΓΕΙΟ ΟΙΚΟΝΟΜΙΚΩΝ
                  </button>
                  <button
                    onClick={() => handlePopularOrgSelect({ uid: '100054492', label: 'ΥΠΟΥΡΓΕΙΟ ΕΣΩΤΕΡΙΚΩΝ' })}
                    className="popular-org-button"
                  >
                    🏛️ ΥΠΟΥΡΓΕΙΟ ΕΣΩΤΕΡΙΚΩΝ
                  </button>
                  <button
                    onClick={() => handlePopularOrgSelect({ uid: '6174', label: 'ΔΗΜΟΣ ΛΗΜΝΟΥ' })}
                    className="popular-org-button"
                  >
                    🏖️ ΔΗΜΟΣ ΛΗΜΝΟΥ
                  </button>
                  <button
                    onClick={() => handlePopularOrgSelect({ uid: '3', label: 'ΥΠΟΥΡΓΕΙΟ ΠΑΙΔΕΙΑΣ ΚΑΙ ΘΡΗΣΚΕΥΜΑΤΩΝ' })}
                    className="popular-org-button"
                  >
                    📚 ΥΠΟΥΡΓΕΙΟ ΠΑΙΔΕΙΑΣ
                  </button>
                  <button
                    onClick={() => handlePopularOrgSelect({ uid: '100012329', label: 'ΥΠΟΥΡΓΕΙΟ ΠΕΡΙΒΑΛΛΟΝΤΟΣ ΚΑΙ ΕΝΕΡΓΕΙΑΣ' })}
                    className="popular-org-button"
                  >
                    🌱 ΥΠΟΥΡΓΕΙΟ ΠΕΡΙΒΑΛΛΟΝΤΟΣ
                  </button>
                </div>
                <p className="popular-note">{t('organizations.popularNote')}</p>
              </div>
            </div>
          </div>
        ) : loading ? (
          // Loading state
          <div className="loading-container">
            <div className="loading-spinner"></div>
            <h2>{t('organizations.loadingChart')}</h2>
            <p>{t('organizations.loadingMessage')}</p>
          </div>
        ) : error ? (
          // Error state
          <div className="error-container">
            <h2>{t('organizations.errorTitle')}</h2>
            <p>{error}</p>
            <button onClick={() => fetchOrgData(orgUid)} className="retry-button">
              {t('organizations.retry')}
            </button>
          </div>
        ) : orgData ? (
          // Chart display with clean header
          <div className="chart-container">
            <div className="chart-header">
              <h3 className="chart-title">
                {t('organizations.organizationChart')}
              </h3>
              <div className="chart-controls">
                <p className="chart-help-text">
                  {t('organizations.chartHelpText')}
                </p>
              </div>
            </div>
            <div className="chart-content">
              <ReactFlowProvider>
                <OrgChartViewer
                  orgData={orgData}
                  onNodeClick={handleNodeClick}
                />
              </ReactFlowProvider>
            </div>
          </div>
        ) : null}
      </div>

      {/* Add a footer for breathing room */}
      <div className="page-footer">
        <p>{t('organizations.footerText')}</p>
      </div>
    </div>
  );
};

export default OrganizationsPage;
