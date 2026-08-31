import React, { useState, useRef, useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import DjangoLoginForm from './DjangoLoginForm';
import DjangoRegisterForm from './DjangoRegisterForm';
import DjangoPasswordResetRequest from './DjangoPasswordResetRequest';
// Static import is safe: <UserButton> is only RENDERED when a Clerk session
// exists (isClerkAuth), which implies ClerkProvider is mounted in index.js.
// Sign-in goes through the unified DjangoLoginForm modal (which offers Clerk
// when active), so SignInButton is no longer needed here.
import { UserButton } from '@clerk/clerk-react';
import './UserAuth.css';

const UserAuth = () => {
  const { getCurrentPaletteColor } = useTheme();
  const { user, isLoaded, isSignedIn, isClerkAuth, signOut } = useAuth();
  const [showLoginForm, setShowLoginForm] = useState(false);
  const [showRegisterForm, setShowRegisterForm] = useState(false);
  const [showPasswordResetRequest, setShowPasswordResetRequest] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setShowDropdown(false);
      }
    };

    if (showDropdown) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showDropdown]);

  // Wait for the combined auth state before rendering any auth UI.
  if (!isLoaded) {
    return (
      <div className="user-auth">
        <div className="auth-loading">
          <div className="loading-spinner"></div>
        </div>
      </div>
    );
  }

  // Signed in via Clerk — use Clerk's UserButton (account menu, sign out).
  if (isClerkAuth && user) {
    return (
      <div className="user-auth">
        <UserButton
          appearance={{
            elements: {
              avatarBox: {
                width: '40px',
                height: '40px',
                borderLeft: `3px solid ${getCurrentPaletteColor()}`
              }
            }
          }}
        />
      </div>
    );
  }

  // Not signed in — one email sign-in button; the DjangoLoginForm modal it
  // opens offers every active method (Clerk + email) in one place.
  if (!isSignedIn || !user) {
    return (
      <>
        <div className="user-auth">
          <div className="django-auth-buttons">
            <button
              className="sign-in-button"
              onClick={() => setShowLoginForm(true)}
              style={{ borderLeft: `3px solid ${getCurrentPaletteColor()}` }}
            >
              <span className="auth-icon">🔑</span>
              <span className="auth-text">Sign In</span>
            </button>
            <button
              className="sign-up-button"
              onClick={() => setShowRegisterForm(true)}
              style={{
                background: getCurrentPaletteColor(),
                borderLeft: `3px solid ${getCurrentPaletteColor()}`
              }}
            >
              <span className="auth-icon">✨</span>
              <span className="auth-text">Sign Up</span>
            </button>
          </div>
        </div>

        {showLoginForm && (
          <DjangoLoginForm
            onSuccess={() => setShowLoginForm(false)}
            onCancel={() => setShowLoginForm(false)}
            onSwitchToRegister={() => {
              setShowLoginForm(false);
              setShowRegisterForm(true);
            }}
            onForgotPassword={() => {
              setShowLoginForm(false);
              setShowPasswordResetRequest(true);
            }}
          />
        )}

        {showRegisterForm && (
          <DjangoRegisterForm
            onSuccess={() => setShowRegisterForm(false)}
            onCancel={() => setShowRegisterForm(false)}
            onSwitchToLogin={() => {
              setShowRegisterForm(false);
              setShowLoginForm(true);
            }}
          />
        )}

        {showPasswordResetRequest && (
          <DjangoPasswordResetRequest
            onSuccess={() => setShowPasswordResetRequest(false)}
            onCancel={() => setShowPasswordResetRequest(false)}
          />
        )}
      </>
    );
  }

  // Signed in - show user info with dropdown
  return (
    <div className="user-auth" ref={dropdownRef}>
      <button
        className="user-button"
        onClick={() => setShowDropdown(!showDropdown)}
        style={{ borderLeft: `3px solid ${getCurrentPaletteColor()}` }}
      >
        <div className="user-avatar">
          <div className="avatar-fallback">
            {user.email?.[0]?.toUpperCase() || user.username?.[0]?.toUpperCase() || '?'}
          </div>
        </div>
        <div className="user-info">
          <span className="user-name">{user.username || user.email}</span>
          <span className="user-email">{user.email}</span>
        </div>
        <span className={`dropdown-arrow ${showDropdown ? 'expanded' : ''}`}>▼</span>
      </button>

      {showDropdown && (
        <div className="user-dropdown">
          <div className="dropdown-header">
            <div className="header-avatar">
              <div className="header-avatar-fallback">
                {user.email?.[0]?.toUpperCase() || user.username?.[0]?.toUpperCase() || '?'}
              </div>
            </div>
            <div className="header-info">
              <div className="header-name">{user.username || 'User'}</div>
              <div className="header-email">{user.email}</div>
            </div>
          </div>

          <div className="dropdown-section">
            <button
              className="dropdown-item danger"
              onClick={() => {
                signOut();
                setShowDropdown(false);
              }}
            >
              <span className="item-icon">🚪</span>
              <span className="item-text">Sign Out</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default UserAuth;
