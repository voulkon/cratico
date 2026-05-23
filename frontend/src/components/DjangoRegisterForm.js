import React, { useState } from 'react';
import ReactDOM from 'react-dom';
import { useAuth } from '../contexts/AuthContext';
import { useConfig } from '../contexts/ConfigContext';
import { useTranslation } from '../contexts/TranslationContext';
import { useTheme } from '../contexts/ThemeContext';
import './DjangoLoginForm.css';

/**
 * Django Registration Form
 * Simple registration form for Django authentication when Clerk is not available
 */
function DjangoRegisterForm({ onSuccess, onCancel, onSwitchToLogin }) {
  const { register } = useAuth();
  const { minPasswordLength } = useConfig();
  const { t } = useTranslation();
  const { isDarkMode } = useTheme();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    // Validate passwords match
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    // Validate password length
    if (password.length < minPasswordLength) {
      setError(`Password must be at least ${minPasswordLength} characters long`);
      return;
    }

    setLoading(true);

    try {
      const result = await register(email, password);
      if (result.success) {
        // Registration successful - user needs to verify email
        if (result.verification_required) {
          // Show success message
          alert(result.message || 'Registration successful! Please check your email to verify your account.');
          if (onSuccess) onSuccess();
        } else {
          // Old behavior for backward compatibility (if verification is disabled)
          if (onSuccess) onSuccess();
        }
      } else {
        setError(result.error || 'Registration failed');
      }
    } catch (err) {
      setError('An error occurred during registration');
    } finally {
      setLoading(false);
    }
  };

  // Render modal using Portal to document.body (like Clerk does)
  const modalContent = (
    <div className={`django-login-overlay ${isDarkMode ? 'dark' : 'light'}`}>
      <div className="django-login-modal">
        <div className="django-login-header">
          <h2>{t('common.register') || 'Create Account'}</h2>
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
              ⚠️ {error}
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
              placeholder={`At least ${minPasswordLength} characters`}
              required
              disabled={loading}
              minLength={minPasswordLength}
            />
          </div>

          <div className="django-login-field">
            <label htmlFor="confirmPassword">Confirm Password</label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Re-enter your password"
              required
              disabled={loading}
              minLength={minPasswordLength}
            />
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
              {loading ? 'Creating account...' : 'Create Account'}
            </button>
          </div>
        </form>

        <div className="django-login-footer">
          <p>
            Already have an account?{' '}
            <button
              onClick={onSwitchToLogin}
              className="django-login-switch"
              disabled={loading}
            >
              Sign In
            </button>
          </p>
        </div>
      </div>
    </div>
  );

  // Use portal to render at body level, escaping parent containers
  return ReactDOM.createPortal(modalContent, document.body);
}

export default DjangoRegisterForm;
