import React, { createContext, useContext, useMemo } from 'react';
import useIsMobile, { MOBILE_QUERY } from '../hooks/useIsMobile';

/**
 * Shared viewport state.
 *
 * Calls `useIsMobile` ONCE at the app root and exposes the result via context,
 * so components don't each register their own matchMedia/resize listeners.
 *
 * Usage:
 *   const { isMobile } = useViewport();
 *
 * For a one-off, non-shared check you can still call `useIsMobile()` directly.
 */
const ViewportContext = createContext({ isMobile: false });

export function ViewportProvider({ children }) {
  const isMobile = useIsMobile(MOBILE_QUERY);
  const value = useMemo(() => ({ isMobile }), [isMobile]);
  return (
    <ViewportContext.Provider value={value}>
      {children}
    </ViewportContext.Provider>
  );
}

export function useViewport() {
  return useContext(ViewportContext);
}

export default ViewportContext;
