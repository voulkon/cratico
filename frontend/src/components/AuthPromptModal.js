import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../contexts/TranslationContext';
import { useTheme } from '../contexts/ThemeContext';
import DjangoLoginForm from './DjangoLoginForm';
import DjangoRegisterForm from './DjangoRegisterForm';
import DjangoPasswordResetRequest from './DjangoPasswordResetRequest';
import { useAuthConfig } from '../contexts/AuthConfigContext';
// Static import is safe: <SignInButton> is only RENDERED when the backend
// advertises "clerk" in auth_methods, which also means index.js has mounted
// ClerkProvider. No more build-time require().
import { SignInButton } from '@clerk/clerk-react';

/**
 * Modal that prompts users to sign in when they try to access protected features
 * Supports both Clerk (when configured) and Django auth
 *
 * Flow:
 * 1. Explanation screen: shows WHY sign-in is needed + the feature-specific message
 * 2. Auth screen: Clerk sign-in button OR Django login form
 *
 * This ensures users always see the explanation before being asked to log in.
 */
function AuthPromptModal() {
  const { t } = useTranslation();
  const { isLoaded, isSignedIn } = useAuth();
  const { authMethods } = useAuthConfig();
  const clerkActive = authMethods.includes('clerk');
  const { getCurrentPaletteColor } = useTheme();
  const location = useLocation();
  const [isOpen, setIsOpen] = useState(false);
  const [message, setMessage] = useState('');
  const [supertitle, setSupertitle] = useState('');
  const [showAuthForm, setShowAuthForm] = useState(false);
  const [showRegister, setShowRegister] = useState(false);
  const [showPasswordResetRequest, setShowPasswordResetRequest] = useState(false);

  useEffect(() => {
    const handleAuthRequired = (event) => {
      // Don't show auth modal on special pages like email verification or password reset
      const excludedPaths = ['/verify-email', '/reset-password'];
      if (excludedPaths.some(path => location.pathname.startsWith(path))) {
        return;
      }

      // Show modal for both auth types when user is not signed in
      if (isLoaded && !isSignedIn) {
        setMessage(event.detail?.message || t('auth.signInRequired') || 'Please sign in to access this feature');
        setSupertitle(event.detail?.supertitle || '');
        setIsOpen(true);
        // Always start with the explanation screen
        setShowAuthForm(false);
      }
    };

    window.addEventListener('authRequired', handleAuthRequired);

    return () => {
      window.removeEventListener('authRequired', handleAuthRequired);
    };
  }, [isLoaded, isSignedIn, t, location.pathname]);

  // Close and reset all state
  const handleClose = () => {
    setIsOpen(false);
    setShowAuthForm(false);
    setShowRegister(false);
    setShowPasswordResetRequest(false);
  };

  // Don't render if modal is not open
  if (!isOpen) return null;

  // ── Django auth: show login/register/reset forms ──
  // "django" is always in auth_methods, so these forms are always reachable.
  if (showAuthForm) {
    if (showPasswordResetRequest) {
      return (
        <DjangoPasswordResetRequest
          onSuccess={() => {
            handleClose();
          }}
          onCancel={() => {
            setShowPasswordResetRequest(false);
          }}
        />
      );
    }

    if (showRegister) {
      return (
        <DjangoRegisterForm
          onSuccess={() => {
            handleClose();
          }}
          onCancel={() => {
            handleClose();
          }}
          onSwitchToLogin={() => setShowRegister(false)}
        />
      );
    }

    return (
      <DjangoLoginForm
        onSuccess={() => {
          handleClose();
        }}
        onCancel={() => {
          handleClose();
        }}
        onSwitchToRegister={() => setShowRegister(true)}
        onForgotPassword={() => setShowPasswordResetRequest(true)}
      />
    );
  }

  // ── Explanation screen (shown for both Clerk and Django before auth form) ──
  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.5)',
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      zIndex: 9999,
      padding: '20px'
    }}>
      <div style={{
        backgroundColor: 'var(--card-bg, #ffffff)',
        color: 'var(--text-color, #000000)',
        borderRadius: '12px',
        padding: '32px',
        maxWidth: '400px',
        width: '100%',
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.15)',
        textAlign: 'center'
      }}>
        <div style={{
          fontSize: '48px',
          marginBottom: '16px'
        }}>
          🔐
        </div>

        <h2 style={{
          margin: '0 0 12px 0',
          fontSize: '24px',
          fontWeight: '600'
        }}>
          {supertitle ? (
            <>
              <span style={{
                display: 'block',
                fontSize: '14px',
                fontWeight: '500',
                color: 'var(--muted-text, #888888)',
                marginBottom: '4px'
              }}>
                {supertitle}
              </span>
              {t('auth.signInTitle') || 'Sign In Required'}
            </>
          ) : (
            t('auth.signInTitle') || 'Sign In Required'
          )}
        </h2>

        <p style={{
          margin: '0 0 8px 0',
          fontSize: '16px',
          color: 'var(--muted-text, #666666)',
          lineHeight: '1.5'
        }}>
          {message}
        </p>

        {!message && (
          <p style={{
            margin: '0 0 24px 0',
            fontSize: '14px',
            color: 'var(--muted-text, #888888)',
            lineHeight: '1.5',
            fontStyle: 'italic'
          }}>
            {t('auth.signInExplanation') || 'This feature requires an account to work. Please sign in to continue.'}
          </p>
        )}

        <div style={{
          display: 'flex',
          gap: '12px',
          justifyContent: 'center'
        }}>
          <button
            onClick={handleClose}
            style={{
              padding: '12px 24px',
              borderRadius: '8px',
              border: '1px solid var(--border-color, #e0e0e0)',
              backgroundColor: 'transparent',
              color: 'var(--text-color, #000000)',
              cursor: 'pointer',
              fontSize: '16px',
              fontWeight: '500',
              transition: 'background-color 0.2s'
            }}
            onMouseEnter={(e) => {
              e.target.style.backgroundColor = 'var(--hover-bg, #f5f5f5)';
            }}
            onMouseLeave={(e) => {
              e.target.style.backgroundColor = 'transparent';
            }}
          >
            {t('auth.cancel') || 'Cancel'}
          </button>

          {/* Dual auth: offer every active method. Clerk opens its own modal;
              the email option reveals the Django login form in-place. */}
          {clerkActive && (
            <SignInButton mode="modal">
              <button
                onClick={handleClose}
                style={{
                  padding: '12px 24px',
                  borderRadius: '8px',
                  border: 'none',
                  backgroundColor: getCurrentPaletteColor(),
                  color: 'white',
                  cursor: 'pointer',
                  fontSize: '16px',
                  fontWeight: '500',
                  transition: 'background-color 0.2s'
                }}
                onMouseEnter={(e) => {
                  e.target.style.opacity = '0.8';
                }}
                onMouseLeave={(e) => {
                  e.target.style.opacity = '1';
                }}
              >
                {t('auth.signIn') || 'Sign In'}
              </button>
            </SignInButton>
          )}
          <button
            onClick={() => setShowAuthForm(true)}
            style={{
              padding: '12px 24px',
              borderRadius: '8px',
              border: clerkActive ? '1px solid var(--border-color, #e0e0e0)' : 'none',
              backgroundColor: clerkActive ? 'transparent' : getCurrentPaletteColor(),
              color: clerkActive ? 'var(--text-color, #000000)' : 'white',
              cursor: 'pointer',
              fontSize: '16px',
              fontWeight: '500',
              transition: 'background-color 0.2s'
            }}
            onMouseEnter={(e) => {
              e.target.style.opacity = '0.8';
            }}
            onMouseLeave={(e) => {
              e.target.style.opacity = '1';
            }}
          >
            {clerkActive
              ? t('auth.continueWithEmail') || 'Continue with Email'
              : t('auth.signIn') || 'Sign In'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default AuthPromptModal;
