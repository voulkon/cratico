import React from 'react';
import { useAuth } from '../contexts/AuthContext';

/**
 * Access Denied component for stealth mode allowlist
 *
 * Shown when a user is authenticated but not in the allowlist
 */
function AccessDenied() {
  // The combined AuthContext already carries the active session's user
  // (Clerk user when signed in via Clerk, Django user otherwise) — no direct
  // Clerk hook needed here.
  const { user } = useAuth();

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: '100vh',
      backgroundColor: 'var(--bg-color)',
      padding: '20px'
    }}>
      <div style={{
        maxWidth: '600px',
        textAlign: 'center',
        backgroundColor: 'var(--card-bg)',
        padding: '40px',
        borderRadius: '12px',
        boxShadow: '0 4px 6px rgba(0, 0, 0, 0.1)'
      }}>
        <div style={{ fontSize: '64px', marginBottom: '20px' }}>🔒</div>

        <h1 style={{
          fontSize: '28px',
          marginBottom: '16px',
          color: 'var(--text-color)'
        }}>
          Access Restricted
        </h1>

        <p style={{
          fontSize: '16px',
          marginBottom: '24px',
          color: 'var(--text-secondary)',
          lineHeight: '1.6'
        }}>
          Your account is authenticated, but you don't have permission to access this application.
        </p>

        {user?.primaryEmailAddress && (
          <div style={{
            backgroundColor: 'var(--bg-color)',
            padding: '16px',
            borderRadius: '8px',
            marginBottom: '24px'
          }}>
            <p style={{
              fontSize: '14px',
              color: 'var(--text-secondary)',
              marginBottom: '8px'
            }}>
              Signed in as:
            </p>
            <p style={{
              fontSize: '16px',
              fontWeight: 'bold',
              color: 'var(--text-color)'
            }}>
              {user.primaryEmailAddress.emailAddress}
            </p>
          </div>
        )}

        <p style={{
          fontSize: '14px',
          color: 'var(--text-secondary)',
          lineHeight: '1.6'
        }}>
          If you believe this is an error, please contact the administrator to request access.
        </p>

        <button
          onClick={() => window.location.href = '/api/clerk/sign-out'}
          style={{
            marginTop: '24px',
            padding: '12px 24px',
            fontSize: '16px',
            backgroundColor: 'var(--primary-color)',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            transition: 'opacity 0.2s'
          }}
          onMouseOver={(e) => e.target.style.opacity = '0.8'}
          onMouseOut={(e) => e.target.style.opacity = '1'}
        >
          Sign Out
        </button>
      </div>
    </div>
  );
}

export default AccessDenied;
