/**
 * Tests for the runtime-driven combined AuthProvider (unified-auth step 03).
 *
 * Covers:
 * - auth_methods ["django"]         -> no Clerk code executes (useUser never
 *                                      called), Django token flow works.
 * - auth_methods ["clerk","django"] -> Clerk session wins when signed in.
 * - Clerk active but signed out + valid Django token -> Django identity wins.
 * - Config fetch failure            -> falls back to Django-only and still
 *                                      renders (white-page regression test).
 * - useAuth() value shape is identical in every mode.
 */
import React, { act } from 'react';
import { render, screen } from '@testing-library/react';
import { useUser, useAuth as useClerkAuth } from '@clerk/clerk-react';

import apiClient from '../../api/client';
import { AuthConfigProvider } from '../AuthConfigContext';
import { AuthProvider, useAuth } from '../AuthContext';

jest.mock('@clerk/clerk-react', () => ({
  useUser: jest.fn(),
  useAuth: jest.fn(),
  ClerkProvider: ({ children }) => children,
}));

jest.mock('../../api/client', () => ({
  __esModule: true,
  default: { get: jest.fn() },
  setTokenGetter: jest.fn(),
}));

const BASE_CONFIG = {
  authentication: { required: false, allowlist_enabled: false },
  password_requirements: { min_length: 8 },
};

const DJANGO_ONLY_CONFIG = {
  data: { ...BASE_CONFIG, auth_methods: ['django'], clerk_publishable_key: null },
};

const CLERK_AND_DJANGO_CONFIG = {
  data: {
    ...BASE_CONFIG,
    auth_methods: ['clerk', 'django'],
    clerk_publishable_key: 'pk_test_fake',
  },
};

// Captures the latest useAuth() value for assertions on functions.
const captured = {};

const Probe = () => {
  const auth = useAuth();
  captured.auth = auth;
  if (!auth.isLoaded) {
    return <div>booting</div>;
  }
  return (
    <div data-testid="state">
      {JSON.stringify({
        isSignedIn: auth.isSignedIn,
        isClerkAuth: auth.isClerkAuth,
        user: auth.user,
      })}
    </div>
  );
};

const renderAuth = () =>
  render(
    <AuthConfigProvider>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </AuthConfigProvider>
  );

const readState = async () =>
  JSON.parse((await screen.findByTestId('state')).textContent);

const EXPECTED_KEYS = [
  'user',
  'isSignedIn',
  'isLoaded',
  'getToken',
  'signIn',
  'signOut',
  'register',
  'verifyEmail',
  'requestPasswordReset',
  'resetPassword',
  'isClerkAuth',
].sort();

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  global.fetch = jest.fn();
  captured.auth = undefined;
});

describe('django-only mode (auth_methods: ["django"])', () => {
  beforeEach(() => {
    apiClient.get.mockResolvedValue(DJANGO_ONLY_CONFIG);
  });

  it('authenticates via a stored Django token and never touches Clerk', async () => {
    localStorage.setItem('django_auth_token', 'tok123');
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ user: { id: 1, email: 'django@example.com' } }),
    });

    renderAuth();
    const state = await readState();

    expect(state.isSignedIn).toBe(true);
    expect(state.isClerkAuth).toBe(false);
    expect(state.user).toEqual({ id: 1, email: 'django@example.com' });

    // Zero Clerk code executes when "clerk" is not advertised.
    expect(useUser).not.toHaveBeenCalled();
    expect(useClerkAuth).not.toHaveBeenCalled();

    // /auth/me/ was validated with the Django token header. The base URL
    // comes from REACT_APP_API_URL, which differs between environments.
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/auth/me/'),
      expect.objectContaining({
        headers: { Authorization: 'Token tok123' },
      })
    );

    // getToken returns the Django token
    let token;
    await act(async () => {
      token = await captured.auth.getToken();
    });
    expect(token).toBe('tok123');
  });

  it('clears an invalid Django token and reports signed out', async () => {
    localStorage.setItem('django_auth_token', 'stale');
    global.fetch.mockResolvedValue({ ok: false, status: 401 });

    renderAuth();
    const state = await readState();

    expect(state.isSignedIn).toBe(false);
    expect(localStorage.getItem('django_auth_token')).toBeNull();
  });

  it('exposes the full value shape (Django methods available)', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 401 });

    renderAuth();
    await readState();

    expect(Object.keys(captured.auth).sort()).toEqual(EXPECTED_KEYS);
  });
});

describe('clerk+django mode (auth_methods: ["clerk","django"])', () => {
  beforeEach(() => {
    apiClient.get.mockResolvedValue(CLERK_AND_DJANGO_CONFIG);
  });

  it('lets the Clerk session win when signed in via Clerk', async () => {
    const clerkUser = {
      id: 'user_clerk',
      primaryEmailAddress: { emailAddress: 'clerk@example.com' },
    };
    const clerkGetToken = jest.fn().mockResolvedValue('clerk-jwt');
    useUser.mockReturnValue({ user: clerkUser, isSignedIn: true, isLoaded: true });
    useClerkAuth.mockReturnValue({ getToken: clerkGetToken, signOut: jest.fn() });

    renderAuth();
    const state = await readState();

    expect(state.isSignedIn).toBe(true);
    expect(state.isClerkAuth).toBe(true);
    expect(state.user).toEqual(clerkUser);

    // getToken delegates to Clerk
    let token;
    await act(async () => {
      token = await captured.auth.getToken();
    });
    expect(token).toBe('clerk-jwt');
    expect(clerkGetToken).toHaveBeenCalled();

    // Django methods still available for dual auth
    expect(typeof captured.auth.signIn).toBe('function');
    expect(typeof captured.auth.register).toBe('function');
    expect(Object.keys(captured.auth).sort()).toEqual(EXPECTED_KEYS);
  });

  it('falls back to the Django identity when Clerk is active but signed out', async () => {
    useUser.mockReturnValue({ user: null, isSignedIn: false, isLoaded: true });
    useClerkAuth.mockReturnValue({ getToken: jest.fn(), signOut: jest.fn() });

    localStorage.setItem('django_auth_token', 'tok123');
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({ user: { id: 7, email: 'django@example.com' } }),
    });

    renderAuth();
    const state = await readState();

    expect(state.isSignedIn).toBe(true);
    expect(state.isClerkAuth).toBe(false);
    expect(state.user).toEqual({ id: 7, email: 'django@example.com' });

    // getToken returns the Django token, not Clerk's
    let token;
    await act(async () => {
      token = await captured.auth.getToken();
    });
    expect(token).toBe('tok123');
  });

  it('reports signed out when neither mechanism has a session', async () => {
    useUser.mockReturnValue({ user: null, isSignedIn: false, isLoaded: true });
    useClerkAuth.mockReturnValue({ getToken: jest.fn(), signOut: jest.fn() });

    renderAuth();
    const state = await readState();

    expect(state.isSignedIn).toBe(false);
    expect(state.isClerkAuth).toBe(false);
    expect(state.user).toBeNull();
  });
});

describe('config fetch failure', () => {
  it('falls back to Django-only and still renders (white-page regression)', async () => {
    apiClient.get.mockRejectedValue(new Error('network down'));

    renderAuth();
    const state = await readState();

    // App still boots: loaded, signed out, Django-only.
    expect(state.isSignedIn).toBe(false);
    expect(state.isClerkAuth).toBe(false);
    expect(useUser).not.toHaveBeenCalled();
    expect(Object.keys(captured.auth).sort()).toEqual(EXPECTED_KEYS);
  });
});
