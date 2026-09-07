import React, { createContext, useContext, useState, useEffect } from 'react';
import apiClient from '../api/client';

const AuthConfigContext = createContext();

/**
 * AuthConfig Context Provider
 *
 * Fetches authentication configuration from the backend (/api/system/config/auth/)
 * instead of relying on frontend environment variables.
 *
 * This ensures the frontend UI adapts to backend security settings without
 * requiring frontend rebuild or environment variable changes.
 */
export const AuthConfigProvider = ({ children }) => {
  const [config, setConfig] = useState({
    authentication: {
      required: false,
      allowlist_enabled: false,
    },
    password_requirements: {
      min_length: 8,
    },
    // Which auth providers the backend reports as active.
    // Consumed by AuthContext to decide which providers/buttons to render.
    auth_methods: ['django'],
    // Only set when 'clerk' is in auth_methods; otherwise null.
    clerk_publishable_key: null,
    // Search UX tunables (feature-flag driven, backend-controlled).
    search: {
      debounce_ms: 300,
    },
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchAuthConfig = async () => {
    try {
      setLoading(true);
      const response = await apiClient.get('/system/config/auth/');
      setConfig(response.data);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch auth config:', err);
      setError(err);
      // Keep default config on error (authentication not required)
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAuthConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const value = {
    stealthMode: config.authentication.required,
    stealthAllowlist: config.authentication.allowlist_enabled,
    minPasswordLength: config.password_requirements.min_length,
    authMethods: config.auth_methods ?? ['django'],
    clerkPublishableKey: config.clerk_publishable_key ?? null,
    searchDebounceMs: config.search?.debounce_ms ?? 300,
    loading,
    error,
    refetch: fetchAuthConfig,
  };

  return (
    <AuthConfigContext.Provider value={value}>
      {children}
    </AuthConfigContext.Provider>
  );
};

/**
 * Hook to access auth configuration
 *
 * Usage:
 * ```
 * const { stealthMode, stealthAllowlist, minPasswordLength, authMethods, clerkPublishableKey } = useAuthConfig();
 * ```
 */
export const useAuthConfig = () => {
  const context = useContext(AuthConfigContext);
  if (context === undefined) {
    throw new Error('useAuthConfig must be used within an AuthConfigProvider');
  }
  return context;
};
