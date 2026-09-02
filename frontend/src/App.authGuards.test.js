/**
 * Tests for App's stealth-mode route guards (unified-auth step 04, task 4a/4d).
 *
 * The guards must render from the COMBINED useAuth() state with plain
 * conditional rendering — Clerk's SignedIn/SignedOut/RedirectToSignIn
 * wrappers are gone. Rendering these cases WITHOUT a ClerkProvider pins that
 * regression: any leftover Clerk wrapper would throw
 * "useUser can only be used within the <ClerkProvider /> component".
 *
 * Matrix:
 * - stealth off, signed out            -> public app shell renders.
 * - stealth on, signed in              -> app shell renders.
 * - stealth on, signed out, django     -> LoginPage renders.
 * - stealth on, signed out, clerk+django -> LoginPage renders (no Clerk
 *   components, so no ClerkProvider needed).
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import App from './App';
import { useAuth } from './contexts/AuthContext';
import { useAuthConfig } from './contexts/AuthConfigContext';
import apiClient from './api/client';

jest.mock('./contexts/AuthContext', () => ({
  AuthProvider: ({ children }) => children,
  useAuth: jest.fn(),
}));
jest.mock('./contexts/AuthConfigContext', () => ({
  useAuthConfig: jest.fn(),
}));

// Marker mocks for the two components the guard switches between.
jest.mock('./pages/LoginPage', () => () => <div data-testid="login-page" />);
jest.mock('./pages/HomePage', () => () => <div data-testid="home-page" />);

// Same environment shims as App.test.js: no backend, and react-markdown is
// pure ESM that jest 27 cannot resolve (not exercised here).
// NOTE: CRA jest sets resetMocks:true, so implementations given here are
// wiped before every test — the rejection is re-set in beforeEach below.
jest.mock('./api/client', () => ({
  __esModule: true,
  default: { get: jest.fn() },
  setTokenGetter: jest.fn(),
}));
jest.mock('react-markdown', () => ({ children }) => <div>{children}</div>);
jest.mock('remark-gfm', () => () => {});

// Hermetic Clerk mock: guards must never render Clerk components anymore.
jest.mock('@clerk/clerk-react', () => ({
  SignInButton: ({ children }) => children,
  SignOutButton: ({ children }) => children,
}));

const setup = ({ stealthMode, isSignedIn, authMethods = ['django'] }) => {
  useAuth.mockReturnValue({
    user: isSignedIn ? { id: 1, email: 'user@example.com' } : null,
    isLoaded: true,
    isSignedIn,
    isClerkAuth: false,
    getToken: jest.fn().mockResolvedValue(null),
    signOut: jest.fn(),
  });
  useAuthConfig.mockReturnValue({
    stealthMode,
    stealthAllowlist: false,
    authMethods,
    loading: false,
  });
  return render(<App />);
};

beforeEach(() => {
  jest.clearAllMocks();
  apiClient.get.mockRejectedValue(new Error('no backend in tests'));
  global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 });
});

it('renders the public app shell when stealth mode is off', () => {
  setup({ stealthMode: false, isSignedIn: false });
  expect(screen.getByTestId('home-page')).toBeInTheDocument();
  expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
});

it('renders the app shell in stealth mode when signed in', () => {
  setup({ stealthMode: true, isSignedIn: true });
  expect(screen.getByTestId('home-page')).toBeInTheDocument();
  expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
});

it('renders the login page in stealth mode when signed out (django only)', () => {
  setup({ stealthMode: true, isSignedIn: false, authMethods: ['django'] });
  expect(screen.getByTestId('login-page')).toBeInTheDocument();
  expect(screen.queryByTestId('home-page')).not.toBeInTheDocument();
});

it('renders the login page in stealth mode when signed out (clerk+django)', () => {
  // Regression: previously this path mounted <SignedOut><RedirectToSignIn/>
  // which crashes without ClerkProvider. Plain conditional rendering must not.
  setup({ stealthMode: true, isSignedIn: false, authMethods: ['clerk', 'django'] });
  expect(screen.getByTestId('login-page')).toBeInTheDocument();
  expect(screen.queryByTestId('home-page')).not.toBeInTheDocument();
});
