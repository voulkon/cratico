import React, { useState } from 'react';
import ReactDOM from 'react-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import './DjangoLoginForm.css';

/**
 * Django Password Reset Request Form
 * Allows users to request a password reset email
 */
function DjangoPasswordResetRequest({ onCancel, onSuccess }) {
  const { requestPasswordReset } = useAuth();
  const { isDarkMode } = useTheme();
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);

    try {
      const result = await requestPasswordReset(email);
      if (result.success) {
        setSuccess(result.message || 'Password reset email sent! Please check your inbox.');
        setEmail(''); // Clear the form

        // Close the modal after 3 seconds
        if (onSuccess) {
          setTimeout(() => {
            onSuccess();
          }, 3000);
        }
      } else {
        setError(result.error || 'Failed to send password reset email');
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
          <h2>🔓 Reset Password</h2>
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
            <p className="success-subtitle">Closing in a moment...</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="django-login-form">
            <p className="django-login-description">
              Enter your email address and we'll send you a link to reset your password.
            </p>

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
                {loading ? 'Sending...' : 'Send Reset Link'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );

  return ReactDOM.createPortal(modalContent, document.body);
}

export default DjangoPasswordResetRequest;
