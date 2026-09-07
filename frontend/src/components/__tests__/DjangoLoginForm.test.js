/**
 * Tests for the unified DjangoLoginForm modal (unified-auth follow-up).
 *
 * The modal is the single dual-auth entry point for every call site (user
 * menu, UserAuth, AuthPromptModal, LoginPage):
 * - auth_methods ["clerk","django"] -> "Sign in with Clerk" button + divider
 *   above the email form.
 * - auth_methods ["django"]         -> email form only, zero Clerk UI.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import DjangoLoginForm from '../DjangoLoginForm';
import { useAuth } from '../../contexts/AuthContext';
import { useAuthConfig } from '../../contexts/AuthConfigContext';

jest.mock('../../contexts/AuthContext', () => ({ useAuth: jest.fn() }));
jest.mock('../../contexts/AuthConfigContext', () => ({ useAuthConfig: jest.fn() }));
jest.mock('../../contexts/TranslationContext', () => ({
  useTranslation: () => ({ t: (key) => key }),
}));
jest.mock('../../contexts/ThemeContext', () => ({
  useTheme: () => ({ isDarkMode: false }),
}));

jest.mock('@clerk/clerk-react', () => ({
  SignInButton: ({ children }) => <div data-testid="clerk-sign-in">{children}</div>,
}));

const setup = ({ authMethods }) => {
  useAuth.mockReturnValue({ signIn: jest.fn().mockResolvedValue({ success: true }) });
  useAuthConfig.mockReturnValue({ authMethods });
  return render(
    <DjangoLoginForm
      onSuccess={jest.fn()}
      onCancel={jest.fn()}
      onSwitchToRegister={jest.fn()}
      onForgotPassword={jest.fn()}
    />
  );
};

beforeEach(() => {
  jest.clearAllMocks();
});

describe('dual mode (auth_methods: ["clerk","django"])', () => {
  it('offers the Clerk option above the email form', () => {
    setup({ authMethods: ['clerk', 'django'] });

    expect(screen.getByTestId('clerk-sign-in')).toBeInTheDocument();
    expect(screen.getByText('auth.signInWithClerk')).toBeInTheDocument();
    expect(screen.getByText('auth.orContinueWithEmail')).toBeInTheDocument();
    // The email form is still present below.
    expect(screen.getByLabelText('auth.emailLabel')).toBeInTheDocument();
  });
});

describe('django-only mode (auth_methods: ["django"])', () => {
  it('renders the email form with no Clerk UI', () => {
    setup({ authMethods: ['django'] });

    expect(screen.queryByTestId('clerk-sign-in')).not.toBeInTheDocument();
    expect(screen.queryByText('auth.orContinueWithEmail')).not.toBeInTheDocument();
    expect(screen.getByLabelText('auth.emailLabel')).toBeInTheDocument();
  });
});

describe('email sign-in flow', () => {
  it('calls onSuccess after a successful signIn', async () => {
    const onSuccess = jest.fn();
    useAuth.mockReturnValue({ signIn: jest.fn().mockResolvedValue({ success: true }) });
    useAuthConfig.mockReturnValue({ authMethods: ['django'] });

    render(
      <DjangoLoginForm onSuccess={onSuccess} onCancel={jest.fn()} />
    );

    fireEvent.change(screen.getByLabelText('auth.emailLabel'), {
      target: { value: 'user@example.com' },
    });
    fireEvent.change(screen.getByLabelText('auth.passwordLabel'), {
      target: { value: 'password123' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'auth.signIn' }));

    // signIn resolves async — wait for the success callback.
    await screen.findByLabelText('auth.emailLabel');
    expect(onSuccess).toHaveBeenCalled();
  });
});
