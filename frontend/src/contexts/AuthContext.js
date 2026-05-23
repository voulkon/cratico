import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

const AuthContext = createContext();

// Check if Clerk is available
const isClerkAvailable = () => {
  return !!process.env.REACT_APP_CLERK_PUBLISHABLE_KEY;
};

// Conditionally import Clerk at module level (not inside component)
let useClerkUser, useClerkAuth;
if (isClerkAvailable()) {
  const clerkReact = require('@clerk/clerk-react');
  useClerkUser = clerkReact.useUser;
  useClerkAuth = clerkReact.useAuth;
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

// Clerk-based AuthProvider (when Clerk is configured)
const ClerkAuthProvider = ({ children }) => {
  // Use the hooks imported at module level
  const { user, isSignedIn, isLoaded } = useClerkUser();
  const { getToken, signOut } = useClerkAuth();

  const getAuthToken = async () => {
    try {
      if (isSignedIn && user) {
        return await getToken();
      }
      return null;
    } catch (error) {
      console.error('Error getting Clerk token:', error);
      return null;
    }
  };

  const value = {
    user,
    isSignedIn: isSignedIn && isLoaded,
    isLoaded,
    getToken: getAuthToken,
    signOut,
    isClerkAuth: true,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

// Basic AuthProvider (when Clerk is NOT configured)
// Uses Django session/token authentication
const BasicAuthProvider = ({ children }) => {
  const [isLoaded, setIsLoaded] = useState(false);
  const [user, setUser] = useState(null);
  const [isSignedIn, setIsSignedIn] = useState(false);

  // Use same base URL pattern as axios client
  const apiUrl = process.env.REACT_APP_API_URL || '/api';

  useEffect(() => {
    // Check if user is authenticated via Django session
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
            setUser(data.user);
            setIsSignedIn(true);
          } else {
            // Token invalid, clear it
            localStorage.removeItem('django_auth_token');
          }
        }
      } catch (error) {
        console.error('Error checking auth:', error);
      } finally {
        setIsLoaded(true);
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
        setUser(data.user);
        setIsSignedIn(true);

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

  const getAuthToken = useCallback(async () => {
    // Return Django token for API requests
    return localStorage.getItem('django_auth_token');
  }, []);

  const signOut = useCallback(async () => {
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
      setUser(null);
      setIsSignedIn(false);
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

        // Old behavior: immediate login (for backward compatibility if verification is disabled)
        if (data.token) {
          localStorage.setItem('django_auth_token', data.token);
          setUser(data.user);
          setIsSignedIn(true);
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
          setUser(data.user);
          setIsSignedIn(true);
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
          setUser(data.user);
          setIsSignedIn(true);
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

  const value = {
    user,
    isSignedIn,
    isLoaded,
    getToken: getAuthToken,
    signIn,
    signOut,
    register,
    verifyEmail,
    requestPasswordReset,
    resetPassword,
    isClerkAuth: false,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

// Main AuthProvider that switches between Clerk and Basic auth
export const AuthProvider = ({ children }) => {
  if (isClerkAvailable()) {
    return <ClerkAuthProvider>{children}</ClerkAuthProvider>;
  } else {
    return <BasicAuthProvider>{children}</BasicAuthProvider>;
  }
};
