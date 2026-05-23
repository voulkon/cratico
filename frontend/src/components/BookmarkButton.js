import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { toggleBookmarkForCurrentPage, isCurrentPageBookmarked } from '../api/bookmarks';
import { useTranslation } from '../contexts/TranslationContext';
import { useAuth } from '../contexts/AuthContext';
import SplitButton from './SplitButton';
import './BookmarkButton.css';

/**
 * Split bookmark button for TopControls.
 * Left half: star toggles the bookmark for the current page.
 * Right half: chevron opens/closes the Library sidebar.
 */
export default function BookmarkButton({ onLibraryToggle, isLibraryOpen, bookmarkCount }) {
  const { t } = useTranslation();
  const { isSignedIn, isLoaded } = useAuth();
  const location = useLocation();
  const [isBookmarked, setIsBookmarked] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState('');

  useEffect(() => {
    if (isLoaded && isSignedIn) {
      checkBookmarkStatus();
    } else {
      // Reset bookmark status when not signed in
      setIsBookmarked(false);
    }
  }, [location.pathname, location.search, isSignedIn, isLoaded]);

  async function checkBookmarkStatus() {
    try {
      const bookmark = await isCurrentPageBookmarked();
      setIsBookmarked(!!bookmark);
    } catch (error) {
      console.error('Failed to check bookmark status:', error);
    }
  }

  async function handleToggleBookmark() {
    // Prompt user to sign in if not authenticated
    if (!isSignedIn) {
      window.dispatchEvent(new CustomEvent('authRequired', {
        detail: { message: t('auth.signInToBookmark') || 'Please sign in to bookmark pages' }
      }));
      return;
    }

    setIsLoading(true);
    try {
      const result = await toggleBookmarkForCurrentPage();
      setIsBookmarked(result.action === 'added');

      // Show toast notification
      setToastMessage(result.action === 'added' ? t('library.bookmarked') : t('library.bookmarkRemoved'));
      setShowToast(true);
      setTimeout(() => setShowToast(false), 2000);
    } catch (error) {
      console.error('Failed to toggle bookmark:', error);
      setToastMessage(t('library.errorPrefix') + error.message);
      setShowToast(true);
      setTimeout(() => setShowToast(false), 3000);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <>
      <SplitButton
        isOpen={isLibraryOpen}
        onMainClick={handleToggleBookmark}
        onChevronClick={onLibraryToggle}
        mainActive={isBookmarked}
        mainClassName={`bookmark-button ${isLoading ? 'loading' : ''}`}
        chevronClassName="bookmark-chevron"
        className={`bookmark-split-btn ${isLibraryOpen ? 'library-open' : ''}`}
        mainTitle={isBookmarked ? t('library.removeBookmark') : t('library.bookmarkThisPage')}
        chevronTitle={isLibraryOpen ? t('library.close') : t('library.myLibrary')}
        disabled={isLoading}
      >
        <span className="bookmark-icon">
          {isLoading ? '⋯' : isBookmarked ? '★' : '☆'}
        </span>
      </SplitButton>

      {/* Toast notification */}
      {showToast && (
        <div className="bookmark-toast">
          {toastMessage}
        </div>
      )}
    </>
  );
}
