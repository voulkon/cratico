import { render, screen } from '@testing-library/react';
import App from './App';
import { AuthConfigProvider } from './contexts/AuthConfigContext';

// index.js mounts <AuthConfigProvider> around <App/> — mirror that here.
jest.mock('./api/client', () => ({
  __esModule: true,
  default: { get: jest.fn().mockRejectedValue(new Error('no backend in tests')) },
  setTokenGetter: jest.fn(),
}));

// react-markdown (+ remark/micromark ecosystem) is pure ESM with subpath
// exports jest 27 cannot resolve. It isn't exercised by this smoke test, so
// stub it out.
jest.mock('react-markdown', () => ({ children }) => <div>{children}</div>);
jest.mock('remark-gfm', () => () => {});

global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 });

test('app boots to its loading shell without crashing', () => {
  render(
    <AuthConfigProvider>
      <App />
    </AuthConfigProvider>
  );
  // While the auth config is in flight the app renders its loading shell.
  // (The full routed app is covered by E2E in step 05, not this smoke test.)
  expect(screen.getByText(/loading/i)).toBeInTheDocument();
});
