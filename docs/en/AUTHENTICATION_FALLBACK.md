# Authentication Fallback Configuration

## Overview

The application now supports **flexible authentication** with automatic fallback from Clerk to Django's built-in authentication system. This allows the application to run without requiring Clerk configuration.

## How It Works

### Backend (Django)

The backend checks for Clerk environment variables and:
- **If present**: Enables Clerk JWT authentication alongside Django's standard auth methods
- **If missing**: Uses only Django's built-in authentication (Session, Token, Basic Auth)

### Frontend (React)

The frontend checks for Clerk configuration and:
- **If present**: Wraps the app with `ClerkProvider` and uses Clerk authentication UI
- **If missing**: Runs without Clerk components and allows public access or Django session-based auth

## Environment Variables

### Frontend Variables

- `REACT_APP_CLERK_PUBLISHABLE_KEY` - Clerk publishable key
- `REACT_APP_API_URL` - Backend API URL

### Backend Variables

- `CLERK_JWT_PUBLIC_KEY` - Clerk JWT verification public key
- `CLERK_SECRET_KEY` - Clerk secret key

## Usage Scenarios

### Scenario 1: Full Clerk Authentication (Production)

Set all Clerk environment variables on both frontend and backend:

**Frontend (.env)**
```bash
REACT_APP_CLERK_PUBLISHABLE_KEY=pk_live_xxx
REACT_APP_API_URL=https://api.example.com
```

**Backend (.env)**
```bash
CLERK_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----..."
CLERK_SECRET_KEY=sk_live_xxx
```

**Result**: Full Clerk authentication with sign-in/sign-up UI, JWT tokens, and user management.

---

### Scenario 2: Django Authentication Only (Development/Testing)

**Don't set** Clerk environment variables:

**Frontend (.env)**
```bash
# REACT_APP_CLERK_PUBLISHABLE_KEY not set
REACT_APP_API_URL=http://localhost:8000
```

**Backend (.env)**
```bash
# CLERK_JWT_PUBLIC_KEY not set
# CLERK_SECRET_KEY not set
```

**Result**:
- Frontend runs in public mode without Clerk UI
- Backend accepts Django Session Auth, Token Auth, and Basic Auth
- Perfect for development without needing Clerk setup

---

### Scenario 3: Stealth Mode

Control public access with `STEALTH_MODE`:

**With Clerk (Private App)**
```bash
# Frontend
REACT_APP_CLERK_PUBLISHABLE_KEY=pk_live_xxx
REACT_APP_STEALTH_MODE=true

# Backend
CLERK_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----..."
STEALTH_MODE=true
```
**Result**: Requires Clerk authentication for all access

**Without Clerk (Public App)**
```bash
# Frontend
# REACT_APP_CLERK_PUBLISHABLE_KEY not set
REACT_APP_STEALTH_MODE=false

# Backend
# CLERK_JWT_PUBLIC_KEY not set
STEALTH_MODE=false
```
**Result**: Public access without authentication requirements

## Technical Details

### Backend Changes

**File: `backend/diavgeia_project/settings/rest_framework.py`**
- Dynamically builds authentication class list
- Only includes `ClerkAuthentication` if Clerk credentials are present
- Always includes Django's standard auth methods as fallback

**File: `backend/diavgeia_project/settings/orchestrator.py`**
- Checks for Clerk public key before validation
- Logs informational message when Clerk is not configured
- Doesn't fail if Clerk variables are missing

**File: `backend/api/authentication.py`**
- `ClerkAuthentication.authenticate()` returns `None` if Clerk key is not configured
- Allows other authentication methods to handle the request

### Frontend Changes

**File: `frontend/src/index.js`**
- Conditionally wraps app with `ClerkProvider` only if publishable key exists
- Logs authentication mode for debugging

**File: `frontend/src/contexts/AuthContext.js`**
- `ClerkAuthProvider`: Used when Clerk is available
- `BasicAuthProvider`: Used when Clerk is not available
- Unified interface through `useAuth()` hook
- Added `isClerkAuth` flag to differentiate authentication mode

**File: `frontend/src/App.js`**
- Lazy-loads Clerk components only when needed
- Conditionally uses `SignedIn`, `SignedOut`, `RedirectToSignIn`
- Falls back to direct rendering without Clerk wrapper

**File: `frontend/src/components/AuthPromptModal.js`**
- Only renders auth prompt when Clerk is available
- Lazy-loads `SignInButton` component

**File: `frontend/src/components/AccessDenied.js`**
- Supports both Clerk and non-Clerk user objects
- Lazy-loads Clerk's `useUser` hook

**File: `frontend/src/hooks/useAllowlistCheck.js`**
- Skips allowlist check when Clerk is not available
- Uses unified `useAuth` hook from context

**File: `frontend/src/components/UserAuth.js`**
- Returns `null` when Clerk is not available
- Lazy-loads Clerk button components

**File: `frontend/src/components/UserMenu.js`**
- Conditionally renders sign-in/sign-out buttons
- Supports both Clerk and basic auth sign-out

## Authentication Methods Available

### With Clerk Configured
1. **Clerk JWT Authentication** - Primary method via Bearer tokens
2. **Django Session Authentication** - Fallback for admin/browsable API
3. **Django Token Authentication** - For API keys
4. **Basic Authentication** - For development/testing
5. **API Key Authentication** - For service-to-service

### Without Clerk Configured
1. **Django Session Authentication** - Primary for logged-in users
2. **Django Token Authentication** - For API access
3. **Basic Authentication** - For simple auth
4. **API Key Authentication** - For service-to-service

## Migration Guide

### Disabling Clerk for Development

1. Comment out or remove Clerk variables from `.env` files:
   ```bash
   # REACT_APP_CLERK_PUBLISHABLE_KEY=pk_test_xxx
   # CLERK_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----..."
   # CLERK_SECRET_KEY=sk_test_xxx
   ```

2. Restart frontend and backend services

3. Application will run in public mode without Clerk UI

### Re-enabling Clerk for Production

1. Set Clerk environment variables in production environment
2. Deploy updated configuration
3. Clerk authentication will be automatically enabled

## Logging

The system logs authentication mode on startup:

**Backend logs:**
- `✓ Clerk authentication configured` - When Clerk is enabled
- `ℹ️  Clerk authentication not configured (missing CLERK_JWT_PUBLIC_KEY). Using Django default authentication.` - When Clerk is disabled

**Frontend console logs:**
- `✓ Clerk authentication enabled` - When Clerk is available
- `ℹ️ Clerk authentication not configured. Using Django default authentication.` - When Clerk is not available

## Best Practices

1. **Production**: Always use Clerk for proper user management and security
2. **Development**: Can disable Clerk for faster iteration
3. **Testing**: Use Django auth for integration tests
4. **CI/CD**: Configure based on environment (staging vs production)

## Troubleshooting

### Issue: "Clerk not loading but variables are set"

**Check:**
- Verify environment variables are properly loaded (check browser console and backend logs)
- Ensure no typos in variable names
- Restart services after changing environment variables

### Issue: "Can't authenticate without Clerk"

**Solution:**
- Use Django admin to create users: `python manage.py createsuperuser`
- Use Django Token Authentication with `X-API-KEY` header
- Enable API key authentication for programmatic access

### Issue: "Sign-in button doesn't appear"

**Expected behavior:**
- Without Clerk configured, sign-in UI is hidden
- App runs in public mode or relies on Django session authentication
- To add authentication UI, configure Clerk environment variables

## Security Considerations

1. **Public Mode**: When Clerk is disabled and `STEALTH_MODE=false`, the API is publicly accessible
2. **Protected Mode**: Set `STEALTH_MODE=true` even without Clerk to require Django authentication
3. **API Keys**: Always use API keys for service-to-service communication
4. **Production**: Always use HTTPS with proper JWT verification

## References

- [Clerk Documentation](https://clerk.com/docs)
- [Django REST Framework Authentication](https://www.django-rest-framework.org/api-guide/authentication/)
- [ARCHITECTURE.md](./ARCHITECTURE.md) - System architecture overview
- [ENVIRONMENT_VARIABLES.md](./ENVIRONMENT_VARIABLES.md) - Complete environment variable reference
