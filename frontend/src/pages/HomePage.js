import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useAuth } from '../contexts/AuthContext';
import { useAuthConfig } from '../contexts/AuthConfigContext';
import { DateRangeProvider, useDateRange } from '../contexts/DateRangeContext';
import apiClient from '../api/client';
import SuperSearch from '../components/SuperSearch';
import TopRelationshipPairs from '../components/TopRelationshipPairs';
import DateRangeSelector from '../components/DateRangeSelector';
import './HomePage.css';

/**
 * Dashboard Data Component - uses DateRangeContext
 */
const DashboardData = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { dateRange } = useDateRange();
  const [topOrganizations, setTopOrganizations] = useState([]);
  const [recentDecisions, setRecentDecisions] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadDashboardData = async () => {
    if (!dateRange) return;

    try {
      setLoading(true);

      // Parallel API calls for dashboard data
      const [
        organizationsResponse,
        decisionsResponse
      ] = await Promise.all([
        // Top organizations
        apiClient.get(`/explore/organizations/?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}&limit=6`),

        // Get recent high-value decisions using optimized endpoint
        apiClient.get(
          `/explore/decisions-optimized/?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}&sort_by=entity_amount_desc&page_size=5`
        )
      ]);

      setTopOrganizations(organizationsResponse.data.organizations || []);
      setRecentDecisions(decisionsResponse.data.results || []);

    } catch (error) {
      console.error('Failed to load dashboard data:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDashboardData();
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

  if (loading) {
    return (
      <div className="homepage-loading">
        <div className="loading-spinner"></div>
        <p>{t('homepage.loading')}</p>
      </div>
    );
  }

  return (
    <>
      {/* Top Org×Entity Relationships - Full Width */}
      <TopRelationshipPairs
        limit={6}
        showDirectAssignmentsToggle={true}
        defaultDirectAssignmentsOnly={true}
      />

      {/* Two Column Grid: Organizations & Decisions */}
      <div className="data-grid">
        {/* Top Organizations */}
        <section className="data-section">
          <div className="section-header">
            <h2 className="section-title">{t('homepage.mostActiveOrganizations')}</h2>
            <button
              className="see-all-button"
              onClick={() => navigate(`/explore/temporal/${dateRange.start_date}/${dateRange.end_date}`)}
            >
              {t('homepage.seeAll')} →
            </button>
          </div>
          <div className="organizations-list">
            {topOrganizations.slice(0, 5).map((org, index) => (
              <div
                key={org.uid}
                className="organization-card compact"
                onClick={() => navigate(`/entity/organization/${org.uid}`)}
              >
                <div className="card-rank">#{index + 1}</div>
                <div className="org-info">
                  <h4 className="org-name">{org.label}</h4>
                  <div className="org-stats">
                    <span className="org-decisions">{org.count} {t('homepage.decisions')}</span>
                    <span className="org-amount">{formatAmount(org.total_amount)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Recent High-Value Decisions */}
        <section className="data-section">
          <div className="section-header">
            <h2 className="section-title">{t('homepage.notableRecentDecisions')}</h2>
            <button
              className="see-all-button"
              onClick={() => navigate(`/explore/temporal/${dateRange.start_date}/${dateRange.end_date}?sort_by=amount_desc`)}
            >
              {t('homepage.seeAll')} →
            </button>
          </div>
          <div className="decisions-list compact">
            {recentDecisions.slice(0, 5).map((decision, index) => (
              <div
                key={decision.ada}
                className="decision-item compact clickable"
                onClick={() => navigate(`/decision/${decision.id}`)}
              >
                <div className="card-rank">#{index + 1}</div>
                <div className="decision-content">
                  <div className="decision-subject">
                    {decision.subject.length > 80
                      ? `${decision.subject.substring(0, 80)}...`
                      : decision.subject
                    }
                  </div>
                  <div className="decision-meta">
                    <span className="decision-org">
                      {decision.organization?.label && decision.organization.label.length > 40
                        ? `${decision.organization.label.substring(0, 40)}...`
                        : decision.organization?.label
                      }
                    </span>
                  </div>
                  <div className="decision-amount-compact">
                    {formatAmount(decision.amount)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
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
                marginTop: '48px',
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
