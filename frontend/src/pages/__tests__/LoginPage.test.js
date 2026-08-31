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

jest.mock('../../components/AuthModal', () => (props) => (
  <div data-testid="auth-modal">
    <button data-testid="mock-login-success" onClick={props.onSuccess} />
    <button data-testid="mock-cancel" onClick={props.onCancel} />
  </div>
));

const setup = ({ isSignedIn = false }) => {
  useAuth.mockReturnValue({ isSignedIn });
  return render(<LoginPage />);
};

beforeEach(() => {
  jest.clearAllMocks();
});

describe('unified auth modal', () => {
  it('renders the self-contained auth modal directly', () => {
    setup({});

    expect(screen.getByTestId('auth-modal')).toBeInTheDocument();
  });

  it('navigates home on login success', () => {
    setup({});

    fireEvent.click(screen.getByTestId('mock-login-success'));

    expect(mockNavigate).toHaveBeenCalledWith('/');
  });
});

describe('combined-context redirect', () => {
  it('navigates home once the combined auth state reports signed in', () => {
    setup({ isSignedIn: true });

    expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true });
  });
});
