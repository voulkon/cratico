import { useState, useRef, useCallback, useEffect } from 'react';

const SIDEBAR_MIN_WIDTH = 300;
const SIDEBAR_MAX_WIDTH = 800;
const SIDEBAR_DEFAULT_WIDTH = 400;
const STORAGE_KEY = 'librarySidebarWidth';

/**
 * Hook for managing library sidebar resizing logic.
 * Handles mouse drag resize with min/max constraints and localStorage persistence.
 */
export default function useLibrarySidebarResize() {
  const sidebarRef = useRef(null);
  const resizeHandleRef = useRef(null);

  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? parseInt(saved, 10) : SIDEBAR_DEFAULT_WIDTH;
  });
  const [isResizing, setIsResizing] = useState(false);

  const handleResizeStart = useCallback((e) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  const handleResizeMove = useCallback((e) => {
    if (!isResizing || !sidebarRef.current) return;

    const newWidth = e.clientX;
    if (newWidth >= SIDEBAR_MIN_WIDTH && newWidth <= SIDEBAR_MAX_WIDTH) {
      setSidebarWidth(newWidth);
      sidebarRef.current.style.width = `${newWidth}px`;
    }
  }, [isResizing]);

  const handleResizeEnd = useCallback(() => {
    if (isResizing) {
      setIsResizing(false);
      localStorage.setItem(STORAGE_KEY, sidebarWidth.toString());
    }
  }, [isResizing, sidebarWidth]);

  // Attach global mousemove/mouseup during resize
  useEffect(() => {
    if (isResizing) {
      document.addEventListener('mousemove', handleResizeMove);
      document.addEventListener('mouseup', handleResizeEnd);
      document.body.style.cursor = 'ew-resize';
      document.body.style.userSelect = 'none';

      return () => {
        document.removeEventListener('mousemove', handleResizeMove);
        document.removeEventListener('mouseup', handleResizeEnd);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      };
    }
  }, [isResizing, handleResizeMove, handleResizeEnd]);

  // Apply saved width on mount
  useEffect(() => {
    if (sidebarRef.current) {
      sidebarRef.current.style.width = `${sidebarWidth}px`;
    }
  }, [sidebarWidth]);

  return {
    sidebarRef,
    resizeHandleRef,
    sidebarWidth,
    isResizing,
    handleResizeStart,
  };
}
