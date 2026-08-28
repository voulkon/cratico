/**
 * Tests for the dual login UI (unified-auth step 04, task 4b/4d).
 *
 * - auth_methods ["clerk","django"] -> method picker offers BOTH Clerk and
 *   the Django email form.
 * - auth_methods ["django"]         -> Django form renders directly, zero
 *   Clerk UI (no dead buttons).
 * - Register remains Django-only in dual mode.
 * - The combined-context redirect: a Clerk sign-in flips isSignedIn via
 *   AuthContext, and LoginPage must react by navigating home.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import LoginPage from '../LoginPage';
import { useAuth } from '../../contexts/AuthContext';
import { useAuthConfig } from '../../contexts/AuthConfigContext';

jest.mock('../../contexts/AuthContext', () => ({ useAuth: jest.fn() }));
jest.mock('../../contexts/AuthConfigContext', () => ({ useAuthConfig: jest.fn() }));
jest.mock('../../contexts/TranslationContext', () => ({
  useTranslation: () => ({ t: (key) => key }),
}));

const mockNavigate = jest.fn();
// LoginPage only consumes useNavigate from the router.
jest.mock('react-router-dom', () => ({ useNavigate: () => mockNavigate }));

jest.mock('@clerk/clerk-react', () => ({
  SignInButton: ({ children }) => <div data-testid="clerk-sign-in">{children}</div>,
}));

jest.mock('../../components/DjangoLoginForm', () => (props) => (
  <div data-testid="django-login-form">
    <button data-testid="mock-switch-register" onClick={props.onSwitchToRegister} />
    <button data-testid="mock-cancel" onClick={props.onCancel} />
  </div>
));
jest.mock('../../components/DjangoRegisterForm', () => () => (
  <div data-testid="django-register-form" />
));
jest.mock('../../components/DjangoPasswordResetRequest', () => () => (
  <div data-testid="django-reset-form" />
));

const setup = ({ authMethods, isSignedIn = false }) => {
  useAuth.mockReturnValue({ isSignedIn });
  useAuthConfig.mockReturnValue({ authMethods });
  return render(<LoginPage />);
};

beforeEach(() => {
  jest.clearAllMocks();
});

describe('dual mode (auth_methods: ["clerk","django"])', () => {
  it('offers both Clerk and email sign-in options', () => {
    setup({ authMethods: ['clerk', 'django'] });

    expect(screen.getByTestId('clerk-sign-in')).toBeInTheDocument();
    expect(screen.getByText('auth.continueWithEmail')).toBeInTheDocument();
    // The Django form is a full-screen modal — it must NOT be up yet.
    expect(screen.queryByTestId('django-login-form')).not.toBeInTheDocument();
  });

  it('reveals the Django form via the email option, and cancel goes back', () => {
    setup({ authMethods: ['clerk', 'django'] });

    fireEvent.click(screen.getByText('auth.continueWithEmail'));
    expect(screen.getByTestId('django-login-form')).toBeInTheDocument();
    expect(screen.queryByTestId('clerk-sign-in')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('mock-cancel'));
    expect(screen.getByTestId('clerk-sign-in')).toBeInTheDocument();
    expect(screen.queryByTestId('django-login-form')).not.toBeInTheDocument();
  });

  it('keeps registration Django-only (no Clerk option on the register view)', () => {
    setup({ authMethods: ['clerk', 'django'] });

    fireEvent.click(screen.getByText('auth.continueWithEmail'));
    fireEvent.click(screen.getByTestId('mock-switch-register'));

    expect(screen.getByTestId('django-register-form')).toBeInTheDocument();
    expect(screen.queryByTestId('clerk-sign-in')).not.toBeInTheDocument();
    expect(screen.queryByTestId('django-login-form')).not.toBeInTheDocument();
  });
});

describe('django-only mode (auth_methods: ["django"])', () => {
  it('renders the Django form directly with no Clerk UI', () => {
    setup({ authMethods: ['django'] });

    expect(screen.getByTestId('django-login-form')).toBeInTheDocument();
    expect(screen.queryByTestId('clerk-sign-in')).not.toBeInTheDocument();
    expect(screen.queryByText('auth.continueWithEmail')).not.toBeInTheDocument();
  });
});

describe('combined-context redirect', () => {
  it('navigates home once the combined auth state reports signed in', () => {
    setup({ authMethods: ['clerk', 'django'], isSignedIn: true });

    expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true });
  });
});
