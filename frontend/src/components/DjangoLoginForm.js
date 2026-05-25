import React, { useState } from 'react';
import ReactDOM from 'react-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../contexts/TranslationContext';
import { useTheme } from '../contexts/ThemeContext';
import './DjangoLoginForm.css';

/**
 * Django Login Form
 * Simple email/password form for Django authentication when Clerk is not available
 */
function DjangoLoginForm({ onSuccess, onCancel, onSwitchToRegister, onForgotPassword }) {
  const { signIn } = useAuth();
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
