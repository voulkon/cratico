import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { CheckCircle, XCircle } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import './VerifyEmailPage.css';

/**
 * Email Verification Page
 * Handles the email verification flow when users click the link in their verification email
 */
function VerifyEmailPage() {
  useDocumentTitle('Verify Email');
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { verifyEmail } = useAuth();
  const [status, setStatus] = useState('verifying'); // 'verifying', 'success', 'error'
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    const token = searchParams.get('token');

    if (!token) {
      setStatus('error');
      setError('No verification token provided. Please check your email for the verification link.');
      return;
    }

    // Verify the email
    const verify = async () => {
      try {
        const result = await verifyEmail(token);

        if (result.success) {
          setStatus('success');
          setMessage(result.message || 'Email verified successfully! Redirecting...');

          // Redirect to home page after 2 seconds
          setTimeout(() => {
            navigate('/');
          }, 2000);
        } else {
          setStatus('error');
          setError(result.error || 'Failed to verify email. The link may be expired or invalid.');
        }
      } catch (err) {
        setStatus('error');
        setError('An unexpected error occurred. Please try again.');
      }
    };

    verify();
  }, [searchParams, verifyEmail, navigate]);

  return (
    <div className="verify-email-page">
      <div className="verify-email-container">
        {status === 'verifying' && (
          <div className="verify-status">
            <div className="spinner"></div>
            <h1>Verifying Your Email</h1>
            <p>Please wait while we verify your email address...</p>
          </div>
        )}

        {status === 'success' && (
          <div className="verify-status success">
            <CheckCircle className="icon" size={64} strokeWidth={2} />
            <h1>Email Verified!</h1>
            <p>{message}</p>
            <button
              onClick={() => navigate('/')}
              className="verify-button"
            >
              Go to Home
            </button>
          </div>
        )}

        {status === 'error' && (
          <div className="verify-status error">
            <XCircle className="icon" size={64} strokeWidth={2} />
            <h1>Verification Failed</h1>
            <p>{error}</p>
            <div className="error-actions">
              <button
                onClick={() => navigate('/')}
                className="verify-button"
              >
                Go to Home
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default VerifyEmailPage;
