import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import DjangoPasswordReset from '../components/DjangoPasswordReset';

/**
 * Password Reset Page
 * Handles the password reset link from email
 * URL: /reset-password?token=<reset-token>
 */
function PasswordResetPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [token, setToken] = useState(null);

  useEffect(() => {
    // Get token from URL
    const resetToken = searchParams.get('token');
    if (!resetToken) {
      // No token provided, redirect to home
      console.error('No reset token provided');
      navigate('/');
    } else {
      setToken(resetToken);
    }
  }, [searchParams, navigate]);

  const handleSuccess = () => {
    // After successful password reset, redirect to home or dashboard
    navigate('/');
  };

  const handleCancel = () => {
    // If user cancels, redirect to home
    navigate('/');
  };

  if (!token) {
    return null; // Will redirect
  }

  return (
    <DjangoPasswordReset
      token={token}
      onSuccess={handleSuccess}
      onCancel={handleCancel}
    />
  );
}

export default PasswordResetPage;
