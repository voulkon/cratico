import { useEffect, useState } from 'react';

/**
 * Single source of truth for the app's "mobile" breakpoint.
 *
 * Import this instead of re-declaring the query, so the definition cannot
 * drift between consumers (App.js, ViewportContext, individual pages, ...).
 */
export const MOBILE_QUERY = '(max-width: 768px)';

/**
 * Returns true when the viewport matches a mobile media query.
 *
 * Defaults to the app-wide MOBILE_QUERY breakpoint.
 *
 * Prefer the shared `useViewport()` context when several components need this
 * value, so only one set of listeners is registered.
 *
 * @param {string} query - CSS media query to evaluate.
 * @returns {boolean}
 */
export function useIsMobile(query = MOBILE_QUERY) {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia(query).matches
      : false
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const update = () => setMatches(mql.matches);

    // Re-sync in case the query prop changed between render and effect.
    update();
    mql.addEventListener('change', update);
    // Fallback: the `change` event is not always dispatched (e.g. some browser
    // device-emulation modes and older Safari), so also re-check on resize.
    window.addEventListener('resize', update);
    return () => {
      mql.removeEventListener('change', update);
      window.removeEventListener('resize', update);
    };
  }, [query]);

  return matches;
}

export default useIsMobile;
