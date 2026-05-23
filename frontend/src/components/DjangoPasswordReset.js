import React, { useState } from 'react';
import ReactDOM from 'react-dom';
import { useAuth } from '../contexts/AuthContext';
import { useConfig } from '../contexts/ConfigContext';
import { useTheme } from '../contexts/ThemeContext';
import './DjangoLoginForm.css';

/**
 * Django Password Reset Form
 * Allows users to set a new password using a reset token from email
 */
function DjangoPasswordReset({ token, onCancel, onSuccess }) {
  const { resetPassword } = useAuth();
  const { minPasswordLength } = useConfig();
  const { isDarkMode } = useTheme();
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    // Validate passwords match
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    // Validate password length
    if (newPassword.length < minPasswordLength) {
      setError(`Password must be at least ${minPasswordLength} characters long`);
      return;
    }

    setLoading(true);

    try {
      const result = await resetPassword(token, newPassword);
      if (result.success) {
        setSuccess(result.message || 'Password reset successfully! You are now logged in.');

        // Call onSuccess after a short delay to show the success message
        if (onSuccess) {
          setTimeout(() => {
            onSuccess();
          }, 2000);
        }
      } else {
        setError(result.error || 'Failed to reset password');
      }
    } catch (err) {
      setError('An error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const modalContent = (
    <div className={`django-login-overlay ${isDarkMode ? 'dark' : 'light'}`}>
      <div className="django-login-modal">
        <div className="django-login-header">
          <h2>🔑 Set New Password</h2>
          <button
            className="django-login-close"
            onClick={onCancel}
            disabled={loading}
          >
            ✕
          </button>
        </div>

        {success ? (
          <div className="django-login-success-message">
            <div className="success-icon">✓</div>
            <p>{success}</p>
            <p className="success-subtitle">Redirecting...</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="django-login-form">
            <p className="django-login-description">
              Please enter your new password below.
            </p>

            {error && (
              <div className="django-login-error">
                ⚠️ {error}
              </div>
            )}

            <div className="django-login-field">
              <label htmlFor="newPassword">New Password</label>
              <input
                id="newPassword"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder={`Enter new password (min ${minPasswordLength} characters)`}
                required
                disabled={loading}
                autoFocus
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
                placeholder="Confirm new password"
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
                {loading ? 'Resetting...' : 'Reset Password'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );

  return ReactDOM.createPortal(modalContent, document.body);
}

export default DjangoPasswordReset;
