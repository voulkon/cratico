import React, { useEffect } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { SignedIn, SignedOut, RedirectToSignIn } from "@clerk/clerk-react";
import HomePage from "./pages/HomePage";
import DevPage from "./pages/OrganizationsPage";
import EntityDetailPage from "./pages/EntityDetailPage";
import DecisionDetailPage from "./pages/DecisionDetailPage";
import AFMEntityDetailPage from "./pages/AFMEntityDetailPage";
import RelationshipDetailPage from "./pages/RelationshipDetailPage";
import NotificationBatchDetailPage from "./pages/NotificationBatchDetailPage";
import SubscriptionHistoryPage from "./pages/SubscriptionHistoryPage";
import SearchResults from "./pages/SearchResults";
import SuperSearchExample from "./pages/SuperSearchExample";
import LibraryPage from "./pages/LibraryPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";
import LoginPage from "./pages/LoginPage";
import PersonPage from "./pages/PersonPage";
import Clock from "./components/Clock";
import AccessDenied from "./components/AccessDenied";
import LibrarySidebar from "./components/LibrarySidebar";
import NotificationSidebar from "./components/NotificationSidebar";
import { ThemeProvider } from './contexts/ThemeContext';
import { AuthProvider } from './contexts/AuthContext';
import { AuthConfigProvider, useAuthConfig } from './contexts/AuthConfigContext';
import { ConfigProvider } from './contexts/ConfigContext';
import { TranslationProvider } from './contexts/TranslationContext';
import { useAllowlistCheck } from './hooks/useAllowlistCheck';
import TopControls from './components/TopControls';
import './index.css';
import RateLimitIndicator from './components/RateLimitIndicator';
import RateLimitModal from './components/RateLimitModal';
import AuthPromptModal from './components/AuthPromptModal';
import { setTokenGetter } from './api/client';
import { useTranslation } from './contexts/TranslationContext';
import { useAuth } from './contexts/AuthContext';
import PasswordResetPage from './pages/PasswordResetPage';

// Check if Clerk is available
const isClerkAvailable = () => {
  return !!process.env.REACT_APP_CLERK_PUBLISHABLE_KEY;
};

// Separate component to access auth context
function AuthenticatedApp({ controlsLayout }) {
  const { getToken, isClerkAuth } = useAuth();
  const { t } = useTranslation(); // OK here - this component is inside TranslationProvider
  const location = useLocation(); // Get current route
  const { stealthAllowlist } = useAuthConfig();
  const { isAllowed, isChecking } = useAllowlistCheck();

  // Check if we're on the homepage
  const isHomePage = location.pathname === '/';

  // Check if we're on special auth pages (hide UI chrome)
  const isAuthPage = location.pathname === '/verify-email' || location.pathname === '/reset-password';

  // Library sidebar state
  const [isLibraryOpen, setIsLibraryOpen] = React.useState(false);
  const [bookmarkCount, setBookmarkCount] = React.useState(0);

  // Notification sidebar state
  const [isNotificationSidebarOpen, setIsNotificationSidebarOpen] = React.useState(false);

  // User menu state
  const [isUserMenuOpen, setIsUserMenuOpen] = React.useState(false);

  // Toggle handlers with mutual exclusivity - only one can be open at a time
  const handleLibraryToggle = () => {
    setIsLibraryOpen(!isLibraryOpen);
    if (!isLibraryOpen) {
      // Opening library, close others
      setIsNotificationSidebarOpen(false);
      setIsUserMenuOpen(false);
    }
  };

  const handleNotificationToggle = () => {
    setIsNotificationSidebarOpen(!isNotificationSidebarOpen);
    if (!isNotificationSidebarOpen) {
      // Opening notifications, close others
      setIsLibraryOpen(false);
      setIsUserMenuOpen(false);
    }
  };

  const handleUserMenuToggle = () => {
    setIsUserMenuOpen(!isUserMenuOpen);
    if (!isUserMenuOpen) {
      // Opening user menu, close others
      setIsLibraryOpen(false);
      setIsNotificationSidebarOpen(false);
    }
  };

  // Handler for closing any open component when overlay is clicked
  const handleOverlayClick = () => {
    setIsLibraryOpen(false);
    setIsNotificationSidebarOpen(false);
    setIsUserMenuOpen(false);
  };

  // Check if any component is open
  const isAnyOpen = isLibraryOpen || isNotificationSidebarOpen || isUserMenuOpen;

  // Set up the token getter for API client
  useEffect(() => {
    setTokenGetter(getToken, isClerkAuth);
    // eslint-disable-next-line
  }, [getToken, isClerkAuth]);

  // If allowlist is enabled, check if user is allowed
  if (stealthAllowlist) {
    if (isChecking) {
      return (
        <div style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          minHeight: '100vh',
          backgroundColor: 'var(--bg-color)'
        }}>
          <div>{t('library.checkingAccess')}</div>
        </div>
      );
    }

    if (isAllowed === false) {
      return <AccessDenied />;
    }
  }

  return (
    <>
      {/* Unified overlay for all split buttons - shows when any is open */}
      {isAnyOpen && !isAuthPage && (
        <div
          className="unified-overlay"
          onClick={handleOverlayClick}
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.4)',
            zIndex: 1002,
            animation: 'fadeIn 0.2s ease-out'
          }}
        />
      )}

      {/* Flexible top controls with library toggle and bookmark button - hidden on auth pages */}
      {!isAuthPage && (
        <TopControls
          layout={controlsLayout}
          onLibraryToggle={handleLibraryToggle}
          isLibraryOpen={isLibraryOpen}
          bookmarkCount={bookmarkCount}
          onNotificationSidebarToggle={handleNotificationToggle}
          isNotificationSidebarOpen={isNotificationSidebarOpen}
          onUserMenuToggle={handleUserMenuToggle}
          isUserMenuOpen={isUserMenuOpen}
          hideLogo={isHomePage}
        />
      )}

      {/* Library Sidebar - hidden on auth pages */}
      {!isAuthPage && (
        <LibrarySidebar
          isOpen={isLibraryOpen}
          onClose={() => setIsLibraryOpen(false)}
          onBookmarkCountChange={setBookmarkCount}
        />
      )}

      {/* Notification Sidebar - hidden on auth pages */}
      {!isAuthPage && (
        <NotificationSidebar
          isOpen={isNotificationSidebarOpen}
          onClose={() => setIsNotificationSidebarOpen(false)}
        />
      )}

      <RateLimitIndicator />
      <RateLimitModal />
      <AuthPromptModal />

      {/* Content wrapper - adds top offset to clear fixed controls (logo + top buttons) */}
      <div className={!isHomePage && !isAuthPage ? 'app-content' : ''}>
        <Routes>
          {/* NEW: Use HomePage as the main landing page */}
          <Route path="/" element={<HomePage />} />

          {/* Email Verification Page */}
          <Route path="/verify-email" element={<VerifyEmailPage />} />

          {/* Library - bookmark management */}
          <Route path="/library" element={<LibraryPage />} />

          {/* RENAMED: Change from /dev to /organizations */}
          <Route path="/organizations" element={<DevPage />} />
          <Route path="/dev" element={<Navigate to="/organizations" />} />

          {/* Search Results Page */}
          <Route path="/search" element={<SearchResults />} />

          {/* Super Search Example Page */}
          <Route path="/search-example" element={<SuperSearchExample />} />

          <Route path="/entity/:entityType/:entityId" element={<EntityDetailPage />} />
          <Route path="/decision/:ada" element={<DecisionDetailPage />} />
          <Route path="/health" element={<Clock />} />
          <Route path="/entity/afm/:afm" element={<AFMEntityDetailPage />} />

          {/* Person page - companies where a person is involved */}
          <Route path="/person/:personName" element={<PersonPage />} />

          {/* Relationship page - Entity × Organization */}
          <Route path="/relationship/entity/:afm/org/:orgUid" element={<RelationshipDetailPage />} />

          {/* Notification Batch Detail */}
          <Route path="/batch/:batchId" element={<NotificationBatchDetailPage />} />

          {/* Subscription History - All decisions from a subscription */}
          <Route path="/notifications/subscriptions/:subscriptionId/history" element={<SubscriptionHistoryPage />} />

          <Route path="/reset-password" element={<PasswordResetPage />} />
        </Routes>
      </div>
    </>
  );
}

// Main App component
function App({ controlsLayout = 'vertical-right' }) {
  // NOTE: Cannot use useTranslation here - this component creates the TranslationProvider
  const clerkAvailable = isClerkAvailable();

  return (
    <TranslationProvider>
      <ThemeProvider>
        <AuthProvider>
          <AuthConfigProvider>
            <ConfigProvider>
              <AppContent
                controlsLayout={controlsLayout}
                clerkAvailable={clerkAvailable}
              />
            </ConfigProvider>
          </AuthConfigProvider>
        </AuthProvider>
      </ThemeProvider>
    </TranslationProvider>
  );
}

// Separate component to access auth context
function AppContent({ controlsLayout, clerkAvailable }) {
  const { isLoaded, isSignedIn, isClerkAuth } = useAuth();
  const { stealthMode, loading: configLoading } = useAuthConfig();

  // Show loading state while checking authentication or fetching config
  if (!isLoaded || configLoading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        backgroundColor: 'var(--bg-color)',
        color: 'var(--text-color)'
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '24px', marginBottom: '16px' }}>Loading...</div>
        </div>
      </div>
    );
  }

  return (
    <Router>
      <div className="App" style={{
        backgroundColor: 'var(--bg-color)',
        color: 'var(--text-color)',
        minHeight: '100vh',
        transition: 'background-color 0.3s ease, color 0.3s ease'
      }}>
        {stealthMode ? (
          // Stealth mode ON - require authentication (Clerk OR Django)
          <>
            {clerkAvailable && isClerkAuth ? (
              // Using Clerk authentication
              <>
                <SignedIn>
                  <AuthenticatedApp controlsLayout={controlsLayout} />
                </SignedIn>
                <SignedOut>
                  <RedirectToSignIn />
                </SignedOut>
              </>
            ) : (
              // Using Django authentication - show login page if not signed in
              <>
                {isSignedIn ? (
                  <AuthenticatedApp controlsLayout={controlsLayout} />
                ) : (
                  <LoginPage />
                )}
              </>
            )}
          </>
        ) : (
          // Stealth mode OFF - public access
          <AuthenticatedApp controlsLayout={controlsLayout} />
        )}
      </div>
    </Router>
  );
}

export default App;
