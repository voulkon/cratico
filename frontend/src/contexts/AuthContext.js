import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
// Static import: Clerk hooks are only *called* inside ClerkStateReader, which
// is only rendered under <ClerkProvider> — so "useUser outside ClerkProvider"
// crashes are structurally impossible. No more conditional require().
import { useUser, useAuth as useClerkAuth } from '@clerk/clerk-react';
import { useAuthConfig } from './AuthConfigContext';

const AuthContext = createContext();

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

/**
 * Reads the Clerk session and reports it upward.
 *
 * Rendered ONLY when the backend advertises "clerk" in auth_methods (which
 * also means index.js has mounted <ClerkProvider>). When Clerk is inactive
 * this component never renders, so zero Clerk code executes and zero network
 * calls to clerk.accounts.dev are made.
 */
const ClerkStateReader = ({ onStateChange }) => {
  const { user, isSignedIn, isLoaded } = useUser();
  const { getToken, signOut } = useClerkAuth();

  useEffect(() => {
    onStateChange({ user, isSignedIn, isLoaded, getToken, signOut });
  }, [user, isSignedIn, isLoaded, getToken, signOut, onStateChange]);

  return null;
};

/**
 * Combined auth provider: serves Clerk and Django auth simultaneously.
 *
 * Merge logic:
 *   1. Clerk active AND Clerk session signed in -> identity = Clerk user.
 *   2. Else if a valid django_auth_token exists -> identity = Django user.
 *   3. Else -> signed out.
 *
 * The Django methods (signIn/register/verifyEmail/requestPasswordReset/
 * resetPassword) are exposed in EVERY mode — that's what makes dual auth
 * usable. `isClerkAuth` tells consumers which mechanism produced the session.
 */
const CombinedAuthProvider = ({ clerkActive, clerkState, configLoading, children }) => {
  const [djangoLoaded, setDjangoLoaded] = useState(false);
  const [djangoUser, setDjangoUser] = useState(null);
  const [djangoSignedIn, setDjangoSignedIn] = useState(false);

  // Use same base URL pattern as axios client
  const apiUrl = process.env.REACT_APP_API_URL || '/api';

  useEffect(() => {
    // Check if user is authenticated via a Django token
    const checkAuth = async () => {
      try {
        const token = localStorage.getItem('django_auth_token');
        if (token) {
          // Verify token is still valid by fetching user info
          const response = await fetch(`${apiUrl}/auth/me/`, {
            headers: {
              'Authorization': `Token ${token}`,
            },
          });

          if (response.ok) {
            const data = await response.json();
            setDjangoUser(data.user);
            setDjangoSignedIn(true);
          } else {
            // Token invalid, clear it
            localStorage.removeItem('django_auth_token');
          }
        }
      } catch (error) {
        console.error('Error checking auth:', error);
      } finally {
        setDjangoLoaded(true);
      }
    };
    checkAuth();
  }, [apiUrl]);

  const signIn = useCallback(async (email, password) => {
    try {
      const response = await fetch(`${apiUrl}/auth/login/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email,
          password
        }),
      });

      if (response.ok) {
        const data = await response.json();
        localStorage.setItem('django_auth_token', data.token);
        setDjangoUser(data.user);
        setDjangoSignedIn(true);

        return { success: true };
      } else {
        const error = await response.json();
        return { success: false, error: error.error || 'Login failed' };
      }
    } catch (error) {
      console.error('Login error:', error);
      return { success: false, error: 'Network error' };
    }
  }, [apiUrl]);

  const getDjangoToken = useCallback(async () => {
    // Return Django token for API requests
    return localStorage.getItem('django_auth_token');
  }, []);

  const djangoSignOut = useCallback(async () => {
    try {
      const token = localStorage.getItem('django_auth_token');
      if (token) {
        await fetch(`${apiUrl}/auth/logout/`, {
          method: 'POST',
          headers: {
            'Authorization': `Token ${token}`,
          },
        });
      }
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      localStorage.removeItem('django_auth_token');
      setDjangoUser(null);
      setDjangoSignedIn(false);
    }
  }, [apiUrl]);

  const register = useCallback(async (email, password) => {
    try {
      const response = await fetch(`${apiUrl}/auth/register/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email,
          password,
          username: email  // Use email as username
        }),
      });

      if (response.ok) {
        const data = await response.json();

        // New behavior: email verification required
        if (data.verification_required) {
          return {
            success: true,
            verification_required: true,
            message: data.message,
            email: data.email
          };
        }

        // Verification disabled: the backend returns a token (and user) so we
        // can sign the user in immediately — no email round-trip exists.
        if (data.token) {
          localStorage.setItem('django_auth_token', data.token);
          // Fall back to a minimal user object if the backend omits one.
          setDjangoUser(data.user || { email: data.email, username: data.email });
          setDjangoSignedIn(true);
        }

        return { success: true, verification_required: false };
      } else {
        const error = await response.json();
        return { success: false, error: error.error || 'Registration failed' };
      }
    } catch (error) {
      console.error('Registration error:', error);
      return { success: false, error: 'Network error' };
    }
  }, [apiUrl]);

  const verifyEmail = useCallback(async (token) => {
    try {
      const response = await fetch(`${apiUrl}/auth/verify-email/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ token }),
      });

      if (response.ok) {
        const data = await response.json();

        // Automatically log the user in after successful verification
        if (data.token) {
          localStorage.setItem('django_auth_token', data.token);
          setDjangoUser(data.user);
          setDjangoSignedIn(true);
        }

        return { success: true, message: data.message };
      } else {
        const error = await response.json();
        return { success: false, error: error.error || 'Verification failed' };
      }
    } catch (error) {
      console.error('Email verification error:', error);
      return { success: false, error: 'Network error' };
    }
  }, [apiUrl]);

  const requestPasswordReset = useCallback(async (email) => {
    try {
      const response = await fetch(`${apiUrl}/auth/request-password-reset/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email }),
      });

      if (response.ok) {
        const data = await response.json();
        return { success: true, message: data.message };
      } else {
        const error = await response.json();
        return { success: false, error: error.error || 'Password reset request failed' };
      }
    } catch (error) {
      console.error('Password reset request error:', error);
      return { success: false, error: 'Network error' };
    }
  }, [apiUrl]);

  const resetPassword = useCallback(async (token, newPassword) => {
    try {
      const response = await fetch(`${apiUrl}/auth/reset-password/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ token, new_password: newPassword }),
      });

      if (response.ok) {
        const data = await response.json();

        // Automatically log the user in after successful password reset
        if (data.token) {
          localStorage.setItem('django_auth_token', data.token);
          setDjangoUser(data.user);
          setDjangoSignedIn(true);
        }

        return { success: true, message: data.message };
      } else {
        const error = await response.json();
        return { success: false, error: error.error || 'Password reset failed' };
      }
    } catch (error) {
      console.error('Password reset error:', error);
      return { success: false, error: 'Network error' };
    }
  }, [apiUrl]);

  // ── Merge Clerk and Django sessions ──────────────────────────────────────
  const clerkReady = clerkActive && clerkState?.isLoaded;
  const useClerkSession = Boolean(clerkReady && clerkState.isSignedIn);

  const getClerkToken = useCallback(async () => {
    try {
      return await clerkState.getToken();
    } catch (error) {
      console.error('Error getting Clerk token:', error);
      return null;
    }
  }, [clerkState]);

  // Sign out of whichever mechanism is active — and clear the other one too,
  // so "sign out" never leaves a residual session behind.
  const signOut = useCallback(async () => {
    if (clerkActive && clerkState?.signOut) {
      try {
        await clerkState.signOut();
      } catch (error) {
        console.error('Clerk sign-out error:', error);
      }
    }
    await djangoSignOut();
  }, [clerkActive, clerkState, djangoSignOut]);

  // Not loaded until (a) the runtime auth config has arrived, (b) the Django
  // token check has finished, and (c) — when Clerk is active — Clerk has
  // reported its session state. Gating on the config prevents a flash of
  // signed-out Django UI while /api/system/config/auth/ is still in flight.
  const isLoaded =
    !configLoading &&
    djangoLoaded &&
    (!clerkActive || Boolean(clerkState?.isLoaded));

  const value = {
    user: useClerkSession ? clerkState.user : djangoUser,
    isSignedIn: useClerkSession ? true : djangoSignedIn,
    isLoaded,
    getToken: useClerkSession ? getClerkToken : getDjangoToken,
    signIn,
    signOut,
    register,
    verifyEmail,
    requestPasswordReset,
    resetPassword,
    isClerkAuth: useClerkSession,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

/**
 * Runtime-driven auth provider. Which mechanisms are active comes from
 * /api/system/config/auth/ (via AuthConfigContext) — never from build-time
 * environment variables.
 *
 * Must be rendered inside AuthConfigProvider, and inside ClerkProvider when
 * the config advertises Clerk (index.js guarantees both).
 */
export const AuthProvider = ({ children }) => {
  const { authMethods, loading: configLoading } = useAuthConfig();
  const clerkActive = !configLoading && authMethods.includes('clerk');
  const [clerkState, setClerkState] = useState(null);

  return (
    <>
      {clerkActive && <ClerkStateReader onStateChange={setClerkState} />}
      <CombinedAuthProvider
        clerkActive={clerkActive}
        clerkState={clerkState}
        configLoading={configLoading}
      >
        {children}
      </CombinedAuthProvider>
    </>
  );
};
