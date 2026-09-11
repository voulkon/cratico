import { render, screen, act } from '@testing-library/react';
import RateLimitIndicator from '../RateLimitIndicator';

describe('RateLimitIndicator', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders the current remaining quota when a fresh rate-limit event arrives', () => {
    render(<RateLimitIndicator label="Requests remaining today" />);

    act(() => {
      window.dispatchEvent(new CustomEvent('rateLimitUpdate', {
        detail: {
          limit: 100,
          remaining: 18,
          reset: 123456,
          updatedAt: Date.now(),
        },
      }));
    });

    const indicator = screen.getByTestId('rate-limit-indicator');
    expect(indicator).toHaveTextContent('18');
    expect(indicator).toHaveTextContent('100');
    expect(indicator).toHaveTextContent('Requests remaining today');
  });

  it('disappears when the rate-limit data is stale', () => {
    const stale = {
      limit: 100,
      remaining: 8,
      reset: 123456,
      updatedAt: Date.now() - (11 * 60 * 1000),
    };

    localStorage.setItem('rateLimitInfo', JSON.stringify(stale));
    render(<RateLimitIndicator label="Requests remaining today" />);

    expect(screen.queryByTestId('rate-limit-indicator')).not.toBeInTheDocument();
  });
});
