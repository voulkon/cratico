# Authentication Configuration

## Overview

The application supports **flexible authentication** with Django's built-in
authentication and Clerk coexisting. Which providers are active is decided
**server-side at runtime** and delivered to the frontend via
`GET /api/system/config/auth/` — there are no build-time auth variables in the
frontend, so the same image serves Clerk and non-Clerk deployments.

## How It Works

### Backend (Django)

The decision function (`backend/api/utils/auth_methods.py`) computes:

```
auth_methods = []
if USE_CLERK_AUTH and CLERK_JWT_PUBLIC_KEY and CLERK_SECRET_KEY and CLERK_PUBLISHABLE_KEY:
    auth_methods += ["clerk"]
auth_methods += ["django"]    # always available (token/session + email login)
```

- `GET /api/system/config/auth/` returns `{ auth_methods, clerk_publishable_key, ... }`.
- The publishable key is a **backend** env var (`CLERK_PUBLISHABLE_KEY`),
  delivered at runtime — no frontend rebuild needed on key rotation.
- DRF always registers Django Token/Session auth; `ClerkAuthentication` is
  appended only when the flag is on, so both mechanisms coexist at the HTTP
  layer.

### Frontend (React)

- `AuthConfigProvider` fetches `/api/system/config/auth/` at boot.
- `index.js` mounts `ClerkProvider` **only** when the backend advertises
  `"clerk"` in `auth_methods` (with the runtime publishable key).
- `AuthContext` is a combined provider: a Clerk session wins when present,
  otherwise the Django token in `localStorage` is used. Django methods
  (signIn/register/verifyEmail/password reset) are available in every mode.
- The login modal (`DjangoLoginForm`) is the single dual-auth entry point:
  when Clerk is active it offers "Sign in with Clerk" above the email form.

## Environment Variables

### Backend Variables

- `USE_CLERK_AUTH` — feature flag (`true`/`false`)
- `CLERK_JWT_PUBLIC_KEY` — Clerk JWT verification public key (PEM)
- `CLERK_SECRET_KEY` — Clerk secret key
- `CLERK_PUBLISHABLE_KEY` — Clerk publishable key (not a secret; backend-owned)

### Frontend Variables

- `REACT_APP_API_URL` — Backend API URL (the only remaining build-time auth-
  related variable; auth methods themselves come from the backend at runtime)

## Usage Scenarios

### Scenario 1: Full Clerk + Django (dual auth)

**Backend (.env)**
```bash
USE_CLERK_AUTH=true
CLERK_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----..."
CLERK_SECRET_KEY=sk_live_xxx
CLERK_PUBLISHABLE_KEY=pk_live_xxx
```

**Result**: `auth_methods = ["clerk", "django"]`. The login modal offers both
Clerk sign-in and the email/password form; both authenticate against the API.

### Scenario 2: Django Authentication Only (Development/Testing)

**Backend (.env)**
```bash
USE_CLERK_AUTH=false
```

**Result**: `auth_methods = ["django"]`. No Clerk JS is loaded (zero requests
to `clerk.accounts.dev`), the login modal shows only the email form.

### Scenario 3: Flag on but keys missing/invalid

**Result**: `auth_methods = ["django"]` + a single backend warning. The app
still boots Django-only — never a white page.

### Scenario 4: Stealth Mode

Control public access with `STEALTH_MODE`:

```bash
STEALTH_MODE=true
```

**Result**: All routes require authentication. The login gate renders from the
same runtime config (`/api/system/config/auth/` stays reachable before login),
offering whichever methods the backend advertises.

## Technical Details

### Backend

- `backend/api/utils/auth_methods.py` — single source of truth
  (`clerk_is_fully_configured`, `get_auth_methods`, `get_clerk_publishable_key`)
- `backend/api/views/system/config.py` — public `auth_config` endpoint
- `backend/diavgeia_project/settings/orchestrator.py` — Clerk key loading +
  the single misconfiguration warning
- `backend/api/authentication.py` — `ClerkAuthentication` double-guards
  (flag + key present) and returns `None` otherwise, letting Django auth handle
  the request

### Frontend

- `frontend/src/contexts/AuthConfigContext.js` — runtime config fetch
  (`authMethods`, `clerkPublishableKey`)
- `frontend/src/index.js` — `ClerkGate` mounts `ClerkProvider` only when the
  backend advertises Clerk
- `frontend/src/contexts/AuthContext.js` — combined provider (Clerk session
  first, Django token fallback; `isClerkAuth` reports which mechanism won)
- `frontend/src/components/DjangoLoginForm.js` — unified login modal with the
  optional Clerk option
- `frontend/src/App.js` — plain conditional rendering against the combined
  `useAuth()` state (no Clerk `SignedIn`/`SignedOut` wrappers)

## Authentication Methods Available

### With Clerk Configured
1. **Clerk JWT Authentication** — Bearer tokens via `ClerkAuthentication`
2. **Django Token Authentication** — for API keys (works alongside Clerk)
3. **Django Session Authentication** — for admin/browsable API
4. **Basic Authentication** — for development/testing
5. **API Key Authentication** — for service-to-service

### Without Clerk Configured
1. **Django Session Authentication** — primary for logged-in users
2. **Django Token Authentication** — for API access
3. **Basic Authentication** — for simple auth
4. **API Key Authentication** — for service-to-service

## Migration Guide

### Disabling Clerk for Development

1. Set `USE_CLERK_AUTH=false` (or clear any of the three Clerk keys) in the
   backend `.env`.
2. Restart the backend. No frontend rebuild is needed.

### Re-enabling Clerk for Production

1. Set `USE_CLERK_AUTH=true` plus all three Clerk keys in the backend env.
2. Restart the backend. The frontend picks the change up on the next page
   load — no rebuild.

## Logging

**Backend logs:**
- `[OK] Clerk JWT public key loaded` — when the flag is on and the key parses
- `[AUTH] Clerk authentication disabled (USE_CLERK_AUTH feature flag is off).` — Django-only
- `[WARN] USE_CLERK_AUTH is enabled but Clerk is not fully configured ...` —
  exactly one line when the flag is on but any key is missing

**Frontend console logs:**
- `✓ Clerk authentication enabled` — when the backend advertises Clerk
- `ℹ️ Clerk authentication not configured. Using Django default authentication.` — Django-only

## Best Practices

1. **Production**: enable Clerk if you need managed user flows; Django auth
   remains available regardless.
2. **Development**: run Django-only (`USE_CLERK_AUTH=false`) for faster
   iteration with zero Clerk network traffic.
3. **Testing**: use Django auth for integration tests.
4. **CI/CD**: configure only backend env vars — the frontend image is
   auth-agnostic.

## Troubleshooting

### Issue: "Clerk not loading but variables are set"

**Check:**
- All three keys (`CLERK_JWT_PUBLIC_KEY`, `CLERK_SECRET_KEY`,
  `CLERK_PUBLISHABLE_KEY`) must be non-empty **and** `USE_CLERK_AUTH=true`.
- Verify `GET /api/system/config/auth/` returns `"clerk"` in `auth_methods`.
- Check the backend startup log for the single `[WARN]` misconfiguration line.

### Issue: "Can't authenticate without Clerk"

**Solution:**
- Use Django admin to create users: `python manage.py createsuperuser`
- Use the email/password form (Django token auth) — it is always available.

### Issue: "Sign-in button doesn't appear"

**Expected behavior:**
- With `STEALTH_MODE=false` and no protected feature triggered, no sign-in UI
  is shown — the app runs in public mode.
- In stealth mode the login page always renders, offering the advertised
  methods.

## Security Considerations

1. **Public Mode**: When Clerk is disabled and `STEALTH_MODE=false`, the API is publicly accessible
2. **Protected Mode**: Set `STEALTH_MODE=true` even without Clerk to require Django authentication
3. **API Keys**: Always use API keys for service-to-service communication
4. **Production**: Always use HTTPS with proper JWT verification
5. **Key rotation**: rotate `CLERK_PUBLISHABLE_KEY` backend-side only — the
   frontend receives it at runtime, no rebuild required

## References

- [Clerk Documentation](https://clerk.com/docs)
- [Django REST Framework Authentication](https://www.django-rest-framework.org/api-guide/authentication/)
- [ENVIRONMENT_VARIABLES.md](./ENVIRONMENT_VARIABLES.md) - Complete environment variable reference
- [Unified auth implementation plan](../implementation-tasks/04.%20unified-auth/00-overview.md)
