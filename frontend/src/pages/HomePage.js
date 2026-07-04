import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useAuth } from '../contexts/AuthContext';
import { useAuthConfig } from '../contexts/AuthConfigContext';
import { DateRangeProvider, useDateRange } from '../contexts/DateRangeContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import SuperSearch from '../components/SuperSearch';
import { GlobeIcon } from '../components/Icons';
import TopRelationshipPairs from '../components/TopRelationshipPairs';
import DateRangeSelector from '../components/DateRangeSelector';
import DashboardGrid from '../components/DashboardGrid';
import OrganizationsSection from '../components/OrganizationsSection';
import DecisionsSection from '../components/DecisionsSection';
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
  const { dateRange } = useDateRange();

  return (
    <DashboardGrid columns={2} collapsible header={<DateRangeSelector />}>
      {/* Featured — Top Org×Entity Relationship Pairs (spans full width) */}
      <DashboardGrid.Featured>
        <TopRelationshipPairs
          limit={6}
          showDirectAssignmentsToggle={true}
          defaultDirectAssignmentsOnly={true}
          className="data-section"
          collapsible
        />
      </DashboardGrid.Featured>

      {/* Column 1 — Most Active Organizations (infinite scroll) */}
      <OrganizationsSection
        onSeeAll={() => navigate(`/explore/temporal/${dateRange.start_date}/${dateRange.end_date}`)}
        collapsible
      />

      {/* Column 2 — Notable Recent Decisions (infinite scroll) */}
      <DecisionsSection
        onSeeAll={() => navigate(`/explore/temporal/${dateRange.start_date}/${dateRange.end_date}?sort_by=amount_desc`)}
        collapsible
      />
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
  const navigate = useNavigate();

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

              {/* Super Search + Browse button */}
              <div className="hero-action-bar">
                <SuperSearch
                  placeholder={t('homepage.searchPlaceholder')}
                  autoFocus={false}
                  showFullResults={true}
                  className="homepage-super-search"
                />
                <button
                  className="homepage-browse-btn"
                  onClick={() => navigate('/browse')}
                  title={t('homepage.browse')}
                >
                  <GlobeIcon size={18} />
                  {t('homepage.browse')}
                </button>
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

              {/* Super Search + Browse button */}
              <div className="hero-action-bar">
                <SuperSearch
                  placeholder={t('homepage.searchPlaceholder')}
                  autoFocus={false}
                  showFullResults={true}
                  className="homepage-super-search"
                />
                <button
                  className="homepage-browse-btn"
                  onClick={() => navigate('/browse')}
                  title={t('homepage.browse')}
                >
                  <GlobeIcon size={18} />
                  {t('homepage.browse')}
                </button>
              </div>
            </div>
          </section>

          {/* Date Range Selector + Dashboard Data — unified card */}
          <DashboardData />
        </div>
      </div>
    </DateRangeProvider>
  );
};

export default HomePage;
