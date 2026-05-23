import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../contexts/TranslationContext';
import { useTheme } from '../contexts/ThemeContext';
import DjangoLoginForm from './DjangoLoginForm';
import DjangoRegisterForm from './DjangoRegisterForm';
import DjangoPasswordResetRequest from './DjangoPasswordResetRequest';

// Check if Clerk is available
const isClerkAvailable = () => {
  return !!process.env.REACT_APP_CLERK_PUBLISHABLE_KEY;
};

// Lazy load SignInButton only if Clerk is available
let SignInButton;
if (isClerkAvailable()) {
  const clerkReact = require('@clerk/clerk-react');
  SignInButton = clerkReact.SignInButton;
}

/**
 * Modal that prompts users to sign in when they try to access protected features
 * Supports both Clerk (when configured) and Django auth
 */
function AuthPromptModal() {
  const { t } = useTranslation();
  const { isLoaded, isSignedIn, isClerkAuth } = useAuth();
  const { getCurrentPaletteColor } = useTheme();
  const location = useLocation();
  const [isOpen, setIsOpen] = useState(false);
  const [message, setMessage] = useState('');
  const [showDjangoForm, setShowDjangoForm] = useState(false);
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
        setIsOpen(true);
        // For Django auth, immediately show the login form
        if (!isClerkAuth) {
          setShowDjangoForm(true);
        }
      }
    };

    window.addEventListener('authRequired', handleAuthRequired);

    return () => {
      window.removeEventListener('authRequired', handleAuthRequired);
    };
  }, [isLoaded, isSignedIn, isClerkAuth, t, location.pathname]);

  // Don't render if modal is not open
  if (!isOpen) return null;

  // For Django auth, show the login form directly
  if (showDjangoForm) {
    if (showPasswordResetRequest) {
      return (
        <DjangoPasswordResetRequest
          onSuccess={() => {
            setIsOpen(false);
            setShowDjangoForm(false);
            setShowPasswordResetRequest(false);
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
            setIsOpen(false);
            setShowDjangoForm(false);
            setShowRegister(false);
          }}
          onCancel={() => {
            setIsOpen(false);
            setShowDjangoForm(false);
            setShowRegister(false);
          }}
          onSwitchToLogin={() => setShowRegister(false)}
        />
      );
    }

    return (
      <DjangoLoginForm
        onSuccess={() => {
          setIsOpen(false);
          setShowDjangoForm(false);
        }}
        onCancel={() => {
          setIsOpen(false);
          setShowDjangoForm(false);
        }}
        onSwitchToRegister={() => setShowRegister(true)}
        onForgotPassword={() => setShowPasswordResetRequest(true)}
      />
    );
  }

  // For Clerk auth, show the auth prompt modal with Clerk sign-in button
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
          {t('auth.signInTitle') || 'Sign In Required'}
        </h2>

        <p style={{
          margin: '0 0 24px 0',
          fontSize: '16px',
          color: 'var(--muted-text, #666666)',
          lineHeight: '1.5'
        }}>
          {message}
        </p>

        <div style={{
          display: 'flex',
          gap: '12px',
          justifyContent: 'center'
        }}>
          <button
            onClick={() => setIsOpen(false)}
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

          <SignInButton mode="modal">
            <button
              onClick={() => setIsOpen(false)}
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
        </div>
      </div>
    </div>
  );
}

export default AuthPromptModal;
