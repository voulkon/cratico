import React from "react";
import ReactDOM from "react-dom/client";
import { ClerkProvider } from '@clerk/clerk-react';
import App from "./App";
import { AuthConfigProvider, useAuthConfig } from './contexts/AuthConfigContext';

const root = ReactDOM.createRoot(document.getElementById("root"));

/**
 * Runtime gate for ClerkProvider.
 *
 * Whether Clerk is active comes from /api/system/config/auth/ (fetched by
 * AuthConfigProvider), NOT from build-time REACT_APP_* variables — so the
 * same image serves Clerk and non-Clerk deployments. While the config is
 * loading, render a minimal splash so the app never mounts under the wrong
 * provider (this is the fix for the white-page class of bugs).
 */
function ClerkGate({ children }) {
  const { authMethods, clerkPublishableKey, loading } = useAuthConfig();

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh'
      }}>
        <div>Loading...</div>
      </div>
    );
  }

  if (authMethods.includes('clerk') && clerkPublishableKey) {
    console.log('✓ Clerk authentication enabled');
    return (
      <ClerkProvider publishableKey={clerkPublishableKey}>
        {children}
      </ClerkProvider>
    );
  }

  console.log('ℹ️ Clerk authentication not configured. Using Django default authentication.');
  return children;
}

root.render(
  <AuthConfigProvider>
    <ClerkGate>
      <App />
    </ClerkGate>
  </AuthConfigProvider>
);
