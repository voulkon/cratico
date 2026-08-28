import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useAuthConfig } from '../contexts/AuthConfigContext';
import { useTranslation } from '../contexts/TranslationContext';
import { useNavigate } from 'react-router-dom';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
// Static import is safe: <SignInButton> is only RENDERED when the backend
// advertises "clerk" in auth_methods (so ClerkProvider is mounted).
import { SignInButton } from '@clerk/clerk-react';
import DjangoLoginForm from '../components/DjangoLoginForm';
import DjangoRegisterForm from '../components/DjangoRegisterForm';
import DjangoPasswordResetRequest from '../components/DjangoPasswordResetRequest';

const LoginPage = () => {
  useDocumentTitle('Login');
  const [showLogin, setShowLogin] = useState(true);
  const [showRegister, setShowRegister] = useState(false);
  const [showPasswordResetRequest, setShowPasswordResetRequest] = useState(false);
  const [showEmailForm, setShowEmailForm] = useState(false);
  const { isSignedIn } = useAuth();
  const { authMethods } = useAuthConfig();
  const { t } = useTranslation();
  const navigate = useNavigate();
  // Dual login UI: offer Clerk alongside the Django form when both are active.
  // Register/password-reset stay Django-only (Clerk runs its own flows).
  const clerkActive = authMethods.includes('clerk');

  // If user is already signed in, redirect to home
  React.useEffect(() => {
    if (isSignedIn) {
      navigate('/', { replace: true });
    }
  }, [isSignedIn, navigate]);

  // Auto-open login modal on mount
  React.useEffect(() => {
    setShowLogin(true);
  }, []);

  const handleLoginSuccess = () => {
    setShowLogin(false);
    navigate('/');
  };

  const handleRegisterSuccess = () => {
    setShowRegister(false);
    setShowLogin(true); // Show login after successful registration
  };

  const handleSwitchToRegister = () => {
    setShowLogin(false);
    setShowRegister(true);
  };

  const handleSwitchToLogin = () => {
    setShowRegister(false);
    setShowLogin(true);
  };

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: '100vh',
      backgroundColor: 'var(--bg-color)',
      color: 'var(--text-color)',
      padding: '20px'
    }}>
      <div style={{
        maxWidth: '500px',
        width: '100%',
        textAlign: 'center'
      }}>
        <h1 style={{ marginBottom: '24px', fontSize: '32px' }}>
          Welcome to Crati
        </h1>
        <p style={{ marginBottom: '32px', color: 'var(--text-secondary)' }}>
          Please sign in to continue
        </p>

        {/* Method picker (dual mode only): the Django form is a full-screen
            modal, so it can't sit next to the Clerk button — the user picks a
            method first. Django-only mode keeps the old direct form. */}
        {clerkActive && showLogin && !showEmailForm && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '16px'
          }}>
            <SignInButton mode="modal">
              <button
                style={{
                  padding: '12px 24px',
                  borderRadius: '8px',
                  border: 'none',
                  backgroundColor: 'var(--accent-color, #4a90d9)',
                  color: 'white',
                  cursor: 'pointer',
                  fontSize: '16px',
                  fontWeight: '500',
                  width: '100%',
                  maxWidth: '320px'
                }}
              >
                {t('auth.signInWithClerk') || 'Sign in with Clerk'}
              </button>
            </SignInButton>
            <button
              onClick={() => setShowEmailForm(true)}
              style={{
                padding: '12px 24px',
                borderRadius: '8px',
                border: '1px solid var(--border-color, #e0e0e0)',
                backgroundColor: 'transparent',
                color: 'var(--text-color)',
                cursor: 'pointer',
                fontSize: '16px',
                fontWeight: '500',
                width: '100%',
                maxWidth: '320px'
              }}
            >
              {t('auth.continueWithEmail') || 'Continue with Email'}
            </button>
          </div>
        )}

        {showLogin && (!clerkActive || showEmailForm) && (
          <DjangoLoginForm
            onSuccess={handleLoginSuccess}
            // In dual mode, cancel returns to the method picker; in
            // Django-only stealth mode there is nothing to go back to.
            onCancel={clerkActive ? () => setShowEmailForm(false) : () => {}}
            onSwitchToRegister={handleSwitchToRegister}
            onForgotPassword={() => {
              setShowLogin(false);
              setShowPasswordResetRequest(true);
            }}
          />
        )}

        {showRegister && (
          <DjangoRegisterForm
            onSuccess={handleRegisterSuccess}
            onCancel={() => {}} // Don't allow closing in stealth mode
            onSwitchToLogin={handleSwitchToLogin}
          />
        )}

        {showPasswordResetRequest && (
          <DjangoPasswordResetRequest
            onSuccess={() => {
              setShowPasswordResetRequest(false);
              setShowLogin(true);
            }}
            onCancel={() => {
              setShowPasswordResetRequest(false);
              setShowLogin(true);
            }}
          />
        )}
      </div>
    </div>
  );
};

export default LoginPage;
