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
        setError(result.error || 'Login failed');
      }
    } catch (err) {
      setError('An error occurred during login');
    } finally {
      setLoading(false);
    }
  };

  // Render modal using Portal to document.body (like Clerk does)
  const modalContent = (
    <div className={`django-login-overlay ${isDarkMode ? 'dark' : 'light'}`}>
      <div className="django-login-modal">
        <div className="django-login-header">
          <h2>{t('common.signIn') || 'Sign In'}</h2>
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
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Enter your email"
              required
              disabled={loading}
              autoFocus
            />
          </div>

          <div className="django-login-field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
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
              Forgot password?
            </button>
          </div>

          <div className="django-login-actions">
            <button
              type="button"
              className="django-login-cancel"
              onClick={onCancel}
              disabled={loading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="django-login-submit"
              disabled={loading}
            >
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </div>
        </form>

        <div className="django-login-footer">
          <p>
            Don't have an account?{' '}
            <button
              onClick={onSwitchToRegister}
              className="django-login-switch"
              disabled={loading}
            >
              Create Account
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
