import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useAuth } from '../contexts/AuthContext';
import { useAuthConfig } from '../contexts/AuthConfigContext';
import { DateRangeProvider, useDateRange } from '../contexts/DateRangeContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import apiClient from '../api/client';
import SuperSearch from '../components/SuperSearch';
import TopRelationshipPairs from '../components/TopRelationshipPairs';
import DateRangeSelector from '../components/DateRangeSelector';
import DashboardGrid, { DashboardSectionHeader, DashboardSectionLoading } from '../components/DashboardGrid';
import './HomePage.css';

/**
 * Home Page Data Component — uses DateRangeContext.
 *
 * Renders a unified DashboardGrid with three columns:
 *   1. Top Org×Entity Relationship Pairs (loads independently)
 *   2. Most Active Organizations
 *   3. Notable Recent Decisions
 *
 * Each column has uniform appearance: card background, scrollable list,
 * section header with "See All" link.
 */
const DashboardData = () => {
  useDocumentTitle('Home');
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { dateRange } = useDateRange();
  const [topOrganizations, setTopOrganizations] = useState([]);
  const [recentDecisions, setRecentDecisions] = useState([]);
  const [gridLoading, setGridLoading] = useState(true);

  const loadGridData = async () => {
    if (!dateRange) return;

    try {
      setGridLoading(true);

      const [
        organizationsResponse,
        decisionsResponse
      ] = await Promise.all([
        apiClient.get(`/explore/organizations/?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}&limit=6`),
        apiClient.get(
          `/explore/decisions-optimized/?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}&sort_by=entity_amount_desc&page_size=5`
        )
      ]);

      setTopOrganizations(organizationsResponse.data.organizations || []);
      setRecentDecisions(decisionsResponse.data.results || []);

    } catch (error) {
      console.error('Failed to load grid data:', error);
    } finally {
      setGridLoading(false);
    }
  };

  useEffect(() => {
    loadGridData();
    // eslint-disable-next-line
  }, [dateRange]);

  const formatAmount = (amount) => {
    if (amount >= 1000000) {
      return `€${(amount / 1000000).toFixed(1)}M`;
    } else if (amount >= 1000) {
      return `€${(amount / 1000).toFixed(0)}K`;
    }
    return `€${amount?.toLocaleString() || 0}`;
  };

  return (
    <DashboardGrid columns={2}>
      {/* Featured — Top Org×Entity Relationship Pairs (spans full width) */}
      <DashboardGrid.Featured>
        <TopRelationshipPairs
          limit={6}
          showDirectAssignmentsToggle={true}
          defaultDirectAssignmentsOnly={true}
          className="data-section"
        />
      </DashboardGrid.Featured>

      {/* Column 1 — Most Active Organizations */}
      {gridLoading ? (
        <DashboardSectionLoading message={t('homepage.loading')} />
      ) : (
        <section className="data-section">
          <DashboardSectionHeader
            title={t('homepage.mostActiveOrganizations')}
            onSeeAll={() => navigate(`/explore/temporal/${dateRange.start_date}/${dateRange.end_date}`)}
          />
          <div className="dashboard-section-info">
            <span>{topOrganizations.length} {t('homepage.organizations') || 'organizations'}</span>
          </div>
          <div className="dashboard-section-scroll">
            {topOrganizations.slice(0, 5).map((org, index) => (
              <button
                key={org.uid}
                className="dashboard-item-card"
                onClick={() => navigate(`/entity/organization/${org.uid}`)}
              >
                <span className="dashboard-rank">#{index + 1}</span>
                <div className="dashboard-item-body">
                  <div className="dashboard-item-title">{org.label}</div>
                  <div className="dashboard-item-meta">
                    <span>{org.count} {t('homepage.decisions')}</span>
                  </div>
                </div>
                <span className="dashboard-item-amount">{formatAmount(org.total_amount)}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Column 2 — Notable Recent Decisions */}
      {gridLoading ? (
        <DashboardSectionLoading message={t('homepage.loading')} />
      ) : (
        <section className="data-section">
          <DashboardSectionHeader
            title={t('homepage.notableRecentDecisions')}
            onSeeAll={() => navigate(`/explore/temporal/${dateRange.start_date}/${dateRange.end_date}?sort_by=amount_desc`)}
          />
          <div className="dashboard-section-info">
            <span>{recentDecisions.length} {t('homepage.decisions')}</span>
          </div>
          <div className="dashboard-section-scroll">
            {recentDecisions.slice(0, 5).map((decision, index) => (
              <button
                key={decision.ada}
                className="dashboard-item-card"
                onClick={() => navigate(`/decision/${decision.id}`)}
              >
                <span className="dashboard-rank">#{index + 1}</span>
                <div className="dashboard-item-body">
                  <div className="dashboard-item-title">
                    {decision.subject.length > 80
                      ? `${decision.subject.substring(0, 80)}...`
                      : decision.subject}
                  </div>
                  <div className="dashboard-item-subtitle">
                    {decision.organization?.label && decision.organization.label.length > 40
                      ? `${decision.organization.label.substring(0, 40)}...`
                      : decision.organization?.label}
                  </div>
                </div>
                <span className="dashboard-item-amount">{formatAmount(decision.amount)}</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </DashboardGrid>
  );
};

/**
 * HomePage Component with Modular Architecture
 */
const HomePage = () => {
  const { t } = useTranslation();
  const { isSignedIn, isLoaded } = useAuth();
  const { stealthMode, loading: configLoading } = useAuthConfig();

  // Show loading state while checking config
  if (configLoading) {
    return (
      <div className="homepage">
        <div className="homepage-container">
          <div className="homepage-loading">
            <div className="loading-spinner"></div>
            <p>{t('homepage.loading')}</p>
          </div>
        </div>
      </div>
    );
  }

  // Show sign-in prompt if stealth mode is enabled and user is not signed in
  if (isLoaded && stealthMode && !isSignedIn) {
    return (
      <div className="homepage">
        <div className="homepage-container">
          {/* Hero Section */}
          <section className="hero-section">
            <div className="hero-content">
              <h1 className="hero-title">
                {t('homepage.title')}
              </h1>
              <p className="hero-subtitle">
                {t('homepage.subtitle')}
              </p>

              {/* Super Search Component - Main Feature */}
              <div className="hero-search-enhanced">
                <SuperSearch
                  placeholder={t('homepage.searchPlaceholder')}
                  autoFocus={false}
                  showFullResults={true}
                  className="homepage-super-search"
                />
              </div>

              {/* Sign-in message */}
              <div style={{
                padding: '24px',
                backgroundColor: 'var(--card-bg, #ffffff)',
                borderRadius: '12px',
                textAlign: 'center',
                maxWidth: '600px',
                margin: '48px auto 0'
              }}>
                <div style={{ fontSize: '48px', marginBottom: '16px' }}>🔐</div>
                <h2 style={{ marginBottom: '12px' }}>
                  {t('homepage.signInRequired') || 'Sign In to Explore'}
                </h2>
                <p style={{ color: 'var(--muted-text, #666666)' }}>
                  {t('homepage.signInMessage') || 'Please sign in to view trending organizations, recent decisions, and more.'}
                </p>
              </div>
            </div>
          </section>
        </div>
      </div>
    );
  }

  return (
    <DateRangeProvider defaultPeriod="week">
      <div className="homepage">
        <div className="homepage-container">
          {/* Hero Section */}
          <section className="hero-section">
            <div className="hero-content">
              <h1 className="hero-title">
                {t('homepage.title')}
              </h1>
              <p className="hero-subtitle">
                {t('homepage.subtitle')}
              </p>

              {/* Super Search Component - Main Feature */}
              <div className="hero-search-enhanced">
                <SuperSearch
                  placeholder={t('homepage.searchPlaceholder')}
                  autoFocus={false}
                  showFullResults={true}
                  className="homepage-super-search"
                />
              </div>
            </div>
          </section>

          {/* Date Range Selector - Controls all dashboard components */}
          <DateRangeSelector />

          {/* Dashboard Data - All components use DateRangeContext */}
          <DashboardData />
        </div>
      </div>
    </DateRangeProvider>
  );
};

export default HomePage;
