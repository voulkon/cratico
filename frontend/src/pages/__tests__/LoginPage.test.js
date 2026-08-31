/**
 * Tests for LoginPage (unified-auth step 04, task 4b/4d — updated for the
 * unified modal).
 *
 * The dual-auth method picker moved INSIDE DjangoLoginForm (it offers
 * "Sign in with Clerk" above the email form when the backend advertises
 * Clerk). LoginPage therefore always renders the DjangoLoginForm directly,
 * regardless of auth_methods — the modal is the single dual-auth entry point.
 *
 * Covered here:
 * - LoginPage renders the unified login modal in every auth_methods config.
 * - Register remains Django-only.
 * - The combined-context redirect: a Clerk sign-in flips isSignedIn via
 *   AuthContext, and LoginPage must react by navigating home.
 * (The Clerk-vs-email branching inside the modal is covered by
 * DjangoLoginForm's own tests.)
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import LoginPage from '../LoginPage';
import { useAuth } from '../../contexts/AuthContext';

jest.mock('../../contexts/AuthContext', () => ({ useAuth: jest.fn() }));

const mockNavigate = jest.fn();
// LoginPage only consumes useNavigate from the router.
jest.mock('react-router-dom', () => ({ useNavigate: () => mockNavigate }));

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

const setup = ({ isSignedIn = false }) => {
  useAuth.mockReturnValue({ isSignedIn });
  return render(<LoginPage />);
};

beforeEach(() => {
  jest.clearAllMocks();
});

describe('unified login modal', () => {
  it('renders the login modal directly (dual mode)', () => {
    setup({});

    expect(screen.getByTestId('django-login-form')).toBeInTheDocument();
  });

  it('renders the login modal directly (django-only mode)', () => {
    setup({});

    expect(screen.getByTestId('django-login-form')).toBeInTheDocument();
  });

  it('keeps registration Django-only', () => {
    setup({});

    fireEvent.click(screen.getByTestId('mock-switch-register'));

    expect(screen.getByTestId('django-register-form')).toBeInTheDocument();
    expect(screen.queryByTestId('django-login-form')).not.toBeInTheDocument();
  });
});

describe('combined-context redirect', () => {
  it('navigates home once the combined auth state reports signed in', () => {
    setup({ isSignedIn: true });

    expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true });
  });
});
