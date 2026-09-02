import React from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import AuthModal from '../components/AuthModal';

const LoginPage = () => {
  useDocumentTitle('Login');
  const { isSignedIn } = useAuth();
  const navigate = useNavigate();
  // The AuthModal is self-contained: it owns login ⇄ register ⇄ reset
  // switching and offers Clerk above the email form when the backend
  // advertises it. Register/password-reset stay Django-only (Clerk runs its
  // own flows).

  // If user is already signed in, redirect to home
  React.useEffect(() => {
    if (isSignedIn) {
      navigate('/', { replace: true });
    }
  }, [isSignedIn, navigate]);

  const handleLoginSuccess = () => {
    navigate('/');
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

        <AuthModal
          onSuccess={handleLoginSuccess}
          // Stealth mode: there is nothing to go back to.
          onCancel={() => {}}
        />
      </div>
    </div>
  );
};

export default LoginPage;
