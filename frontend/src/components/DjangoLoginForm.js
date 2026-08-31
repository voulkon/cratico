import React, { useState } from 'react';
import ReactDOM from 'react-dom';
import { useAuth } from '../contexts/AuthContext';
import { useAuthConfig } from '../contexts/AuthConfigContext';
import { useTranslation } from '../contexts/TranslationContext';
import { useTheme } from '../contexts/ThemeContext';
// Static import is safe: <SignInButton> is only RENDERED when the backend
// advertises "clerk" in auth_methods (so ClerkProvider is mounted in index.js).
import { SignInButton } from '@clerk/clerk-react';
import './DjangoLoginForm.css';

/**
 * Unified Login Modal
 *
 * Email/password form for Django authentication — plus a "Sign in with Clerk"
 * option at the top when the backend advertises Clerk. This makes the modal
 * the single dual-auth entry point for every call site (user menu, UserAuth,
 * AuthPromptModal, LoginPage): one button anywhere opens one modal offering
 * every active method.
 */
function DjangoLoginForm({ onSuccess, onCancel, onSwitchToRegister, onForgotPassword }) {
  const { signIn } = useAuth();
  const { authMethods } = useAuthConfig();
  const clerkActive = authMethods.includes('clerk');
  const { t } = useTranslation();
  const { isDarkMode } = useTheme();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const result = await signIn(email, password);
      if (result.success) {
        if (onSuccess) onSuccess();
      } else {
        setError(result.error || t('auth.loginFailed'));
      }
    } catch (err) {
      setError(t('auth.loginError'));
    } finally {
      setLoading(false);
    }
  };

  // Render modal using Portal to document.body (like Clerk does)
  const modalContent = (
    <div className={`django-login-overlay ${isDarkMode ? 'dark' : 'light'}`}>
      <div className="django-login-modal">
        <div className="django-login-header">
          <h2>{t('auth.signIn')}</h2>
          <button
            className="django-login-close"
            onClick={onCancel}
            disabled={loading}
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="django-login-form">
          {error && (
            <div className="django-login-error">
              {error}
            </div>
          )}

          {/* Dual auth: Clerk option above the email form, visually separated.
              Clerk opens its own modal; onSuccess fires via the combined
              AuthContext when the Clerk session lands. */}
          {clerkActive && (
            <>
              <SignInButton mode="modal">
                <button
                  type="button"
                  className="django-login-clerk"
                  style={{
                    width: '100%',
                    padding: '12px',
                    marginBottom: '4px',
                    borderRadius: '8px',
                    border: 'none',
                    backgroundColor: 'var(--accent-color, #4a90d9)',
                    color: 'white',
                    cursor: 'pointer',
                    fontSize: '15px',
                    fontWeight: '500'
                  }}
                >
                  {t('auth.signInWithClerk') || 'Sign in with Clerk'}
                </button>
              </SignInButton>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  margin: '12px 0',
                  color: 'var(--text-muted, #888)',
                  fontSize: '13px'
                }}
              >
                <span style={{ flex: 1, height: '1px', backgroundColor: 'var(--border-color, #e0e0e0)' }} />
                {t('auth.orContinueWithEmail') || 'or continue with email'}
                <span style={{ flex: 1, height: '1px', backgroundColor: 'var(--border-color, #e0e0e0)' }} />
              </div>
            </>
          )}

          <div className="django-login-field">
            <label htmlFor="email">{t('auth.emailLabel')}</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t('auth.emailPlaceholder')}
              required
              disabled={loading}
              autoFocus
            />
          </div>

          <div className="django-login-field">
            <label htmlFor="password">{t('auth.passwordLabel')}</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t('auth.passwordPlaceholder')}
              required
              disabled={loading}
            />
          </div>

          <div className="django-login-forgot-password">
            <button
              type="button"
              onClick={onForgotPassword}
              className="django-login-forgot-link"
              disabled={loading}
            >
              {t('auth.forgotPassword')}
            </button>
          </div>

          <div className="django-login-actions">
            <button
              type="button"
              className="django-login-cancel"
              onClick={onCancel}
              disabled={loading}
            >
              {t('auth.cancel')}
            </button>
            <button
              type="submit"
              className="django-login-submit"
              disabled={loading}
            >
              {loading ? t('auth.signingIn') : t('auth.signIn')}
            </button>
          </div>
        </form>

        <div className="django-login-footer">
          <p>
            {t('auth.noAccount')}{' '}
            <button
              onClick={onSwitchToRegister}
              className="django-login-switch"
              disabled={loading}
            >
              {t('auth.createAccount')}
            </button>
          </p>
        </div>
      </div>
    </div>
  );

  // Use portal to render at body level, escaping parent containers
  return ReactDOM.createPortal(modalContent, document.body);
}

export default DjangoLoginForm;
