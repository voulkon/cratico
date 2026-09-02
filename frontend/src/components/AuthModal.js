import React, { useState } from 'react';
import DjangoLoginForm from './DjangoLoginForm';
import DjangoRegisterForm from './DjangoRegisterForm';
import DjangoPasswordResetRequest from './DjangoPasswordResetRequest';

/**
 * Self-contained auth modal.
 *
 * Owns the login ⇄ register ⇄ password-reset view switching internally, so
 * callers only render:
 *
 *   <AuthModal onSuccess={...} onCancel={...} />
 *
 * and can never forget to wire the switch callbacks — the exact bug where
 * UserMenu rendered <DjangoLoginForm> without onSwitchToRegister, leaving the
 * "Create Account" button inert (onClick={undefined}).
 *
 * Props:
 * - onSuccess:         called when login succeeds (token stored). Required-ish.
 * - onCancel:          close handler (X button / cancel). May be a no-op when
 *                      there is nothing to go back to (stealth LoginPage).
 * - onRegisterSuccess: optional. Default: switch back to the login view. Pass
 *                      a close handler to dismiss the modal instead.
 * - initialView:       'login' (default) | 'register'. Applies at mount; the
 *                      modal unmounts/remounts to change entry point.
 */
function AuthModal({ onSuccess, onCancel, onRegisterSuccess, initialView = 'login' }) {
  const [view, setView] = useState(initialView);

  if (view === 'register') {
    return (
      <DjangoRegisterForm
        onSuccess={() => {
          if (onRegisterSuccess) {
            onRegisterSuccess();
          } else {
            // Default: back to login so the user can sign in with the new
            // account (or follow the verification-email instructions).
            setView('login');
          }
        }}
        onCancel={onCancel}
        onSwitchToLogin={() => setView('login')}
      />
    );
  }

  if (view === 'reset') {
    return (
      <DjangoPasswordResetRequest
        onSuccess={() => setView('login')}
        onCancel={() => setView('login')}
      />
    );
  }

  return (
    <DjangoLoginForm
      onSuccess={onSuccess}
      onCancel={onCancel}
      onSwitchToRegister={() => setView('register')}
      onForgotPassword={() => setView('reset')}
    />
  );
}

export default AuthModal;
