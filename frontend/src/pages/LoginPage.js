import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import DjangoLoginForm from '../components/DjangoLoginForm';
import DjangoRegisterForm from '../components/DjangoRegisterForm';
import DjangoPasswordResetRequest from '../components/DjangoPasswordResetRequest';

const LoginPage = () => {
  useDocumentTitle('Login');
  const [showLogin, setShowLogin] = useState(true);
  const [showRegister, setShowRegister] = useState(false);
  const [showPasswordResetRequest, setShowPasswordResetRequest] = useState(false);
  const { isSignedIn } = useAuth();
  const navigate = useNavigate();

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

        {showLogin && (
          <DjangoLoginForm
            onSuccess={handleLoginSuccess}
            onCancel={() => {}} // Don't allow closing in stealth mode
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
