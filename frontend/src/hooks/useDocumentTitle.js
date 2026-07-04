import { useEffect } from 'react';

/**
 * Sets the browser tab title. Restores the previous title on unmount.
 * @param {string} title - The page-specific title. "CratiCo" is appended automatically.
 *   Pass null/undefined to just show "CratiCo".
 */
export function useDocumentTitle(title) {
  useEffect(() => {
    const prevTitle = document.title;
    document.title = title ? `${title} — CratiCo` : 'CratiCo';
    return () => {
      document.title = prevTitle;
    };
  }, [title]);
}
