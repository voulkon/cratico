import React, { useState, useRef, useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import DjangoLoginForm from './DjangoLoginForm';
import DjangoRegisterForm from './DjangoRegisterForm';
import DjangoPasswordResetRequest from './DjangoPasswordResetRequest';
import './UserAuth.css';

// Check if Clerk is available
const isClerkAvailable = () => {
  return !!process.env.REACT_APP_CLERK_PUBLISHABLE_KEY;
};

// Lazy load Clerk components only if available
let SignInButton, SignUpButton, UserButton;
if (isClerkAvailable()) {
  const clerkReact = require('@clerk/clerk-react');
  SignInButton = clerkReact.SignInButton;
  SignUpButton = clerkReact.SignUpButton;
  UserButton = clerkReact.UserButton;
}

const UserAuth = () => {
  const { getCurrentPaletteColor } = useTheme();
  const { user, isLoading, isSignedIn, isClerkAuth, signOut } = useAuth();
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

  // Clerk authentication UI
  if (isClerkAuth) {
    if (isLoading) {
      return (
        <div className="user-auth">
          <div className="auth-loading">
            <div className="loading-spinner"></div>
          </div>
        </div>
      );
    }

    // Not signed in - show Clerk sign-in button
    if (!isSignedIn || !user) {
      return (
        <div className="user-auth">
          <SignInButton mode="modal">
            <button
              className="sign-in-button"
              style={{ borderLeft: `3px solid ${getCurrentPaletteColor()}` }}
            >
              <span className="auth-icon">👤</span>
              <span className="auth-text">Sign In</span>
            </button>
          </SignInButton>
        </div>
      );
    }

    // Signed in - use Clerk's UserButton
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

  // Django authentication UI
  if (isLoading) {
    return (
      <div className="user-auth">
        <div className="auth-loading">
          <div className="loading-spinner"></div>
        </div>
      </div>
    );
  }

  // Not signed in - show Django auth buttons
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
