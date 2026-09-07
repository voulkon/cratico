/**
 * Tests for the self-contained AuthModal.
 *
 * Regression coverage for the 2026-09-01 dead-button bug: UserMenu rendered
 * <DjangoLoginForm> without onSwitchToRegister, so the "Create Account"
 * button was inert. AuthModal owns view switching internally, making that
 * wiring mistake impossible — these tests pin the switching behavior.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import AuthModal from '../AuthModal';

jest.mock('../DjangoLoginForm', () => (props) => (
  <div data-testid="login-form">
    <button data-testid="switch-register" onClick={props.onSwitchToRegister} />
    <button data-testid="forgot-password" onClick={props.onForgotPassword} />
    <button data-testid="login-success" onClick={props.onSuccess} />
    <button data-testid="login-cancel" onClick={props.onCancel} />
  </div>
));
jest.mock('../DjangoRegisterForm', () => (props) => (
  <div data-testid="register-form">
    <button data-testid="switch-login" onClick={props.onSwitchToLogin} />
    <button data-testid="register-success" onClick={props.onSuccess} />
  </div>
));
jest.mock('../DjangoPasswordResetRequest', () => (props) => (
  <div data-testid="reset-form">
    <button data-testid="reset-cancel" onClick={props.onCancel} />
  </div>
));

const setup = (props = {}) =>
  render(<AuthModal onSuccess={jest.fn()} onCancel={jest.fn()} {...props} />);

describe('AuthModal view switching', () => {
  it('starts on the login view by default', () => {
    setup();
    expect(screen.getByTestId('login-form')).toBeInTheDocument();
  });

  it('switches login -> register via the in-modal switch', () => {
    setup();
    fireEvent.click(screen.getByTestId('switch-register'));
    expect(screen.getByTestId('register-form')).toBeInTheDocument();
    expect(screen.queryByTestId('login-form')).not.toBeInTheDocument();
  });

  it('switches register -> login', () => {
    setup({ initialView: 'register' });
    fireEvent.click(screen.getByTestId('switch-login'));
    expect(screen.getByTestId('login-form')).toBeInTheDocument();
  });

  it('switches login -> reset and back', () => {
    setup();
    fireEvent.click(screen.getByTestId('forgot-password'));
    expect(screen.getByTestId('reset-form')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('reset-cancel'));
    expect(screen.getByTestId('login-form')).toBeInTheDocument();
  });

  it('register success defaults back to the login view', () => {
    setup();
    fireEvent.click(screen.getByTestId('switch-register'));
    fireEvent.click(screen.getByTestId('register-success'));
    expect(screen.getByTestId('login-form')).toBeInTheDocument();
  });

  it('register success calls onRegisterSuccess when provided', () => {
    const onRegisterSuccess = jest.fn();
    setup({ onRegisterSuccess });
    fireEvent.click(screen.getByTestId('switch-register'));
    fireEvent.click(screen.getByTestId('register-success'));
    expect(onRegisterSuccess).toHaveBeenCalled();
  });

  it('honors initialView="register"', () => {
    setup({ initialView: 'register' });
    expect(screen.getByTestId('register-form')).toBeInTheDocument();
  });
});
