import React, { useState, useEffect } from 'react';
import Logo from './Logo';
import UserMenu from './UserMenu';
import BookmarkButton from './BookmarkButton';
import NotificationButton from './NotificationButton';
import { ChevronRight, ChevronLeft } from './Icons';
import './TopControls.css';

/** Matches the --mobile-breakpoint used in TopControls.css media queries */
const MOBILE = '(max-width: 768px)';

/** One-time check at mount to avoid flash on desktop */
const isMobile = () => window.matchMedia(MOBILE).matches;

/**
 * TopControls - Main navigation bar with logo and action buttons
 *
 * @param {string} layout - Layout mode for the controls:
 *   - 'horizontal-right': Horizontal layout, aligned to the right (default)
 *   - 'vertical-right': Vertical layout from top to bottom, aligned to the right
 *   - 'horizontal-left': Horizontal layout, aligned to the left
 *   - 'vertical-left': Vertical layout from top to bottom, aligned to the left
 *   - 'split-corners': Split layout with logo on left, controls on right
 * @param {boolean} hideLogo - Whether to hide the logo (e.g., on homepage)
 */
const TopControls = ({
  layout = 'horizontal-right',
  onLibraryToggle,
  isLibraryOpen,
  bookmarkCount,
  onNotificationSidebarToggle,
  isNotificationSidebarOpen,
  onUserMenuToggle,
  isUserMenuOpen,
  hideLogo = false
}) => {
  const [isCollapsed, setIsCollapsed] = useState(isMobile);

  // Keep collapsed state in sync with viewport resizes
  useEffect(() => {
    const mql = window.matchMedia(MOBILE);
    const onChange = (e) => setIsCollapsed(e.matches);
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, []);

  const toggleCollapse = () => {
    setIsCollapsed(!isCollapsed);
    // Close any open menus when collapsing
    if (!isCollapsed) {
      if (isUserMenuOpen) onUserMenuToggle();
      if (isLibraryOpen) onLibraryToggle();
      if (isNotificationSidebarOpen) onNotificationSidebarToggle();
    }
  };

  return (
    <>
      {/* Left side: Logo (conditionally rendered) */}
      {!hideLogo && (
        <div className={`left-controls ${isLibraryOpen ? 'shifted' : ''}`}>
          <div className="logo-container">
            <Logo size="small" />
          </div>
        </div>
      )}

      {/* Right side: Collapsible controls */}
      <div className={`top-controls-wrapper ${layout} ${isCollapsed ? 'collapsed' : 'expanded'}`}>
        {/* Collapse/Expand Toggle Button */}
        <button
          className="controls-collapse-toggle"
          onClick={toggleCollapse}
          aria-label={isCollapsed ? 'Expand controls' : 'Collapse controls'}
          title={isCollapsed ? 'Expand controls' : 'Collapse controls'}
        >
          {isCollapsed ? <ChevronLeft size={20} /> : <ChevronRight size={20} />}
        </button>

        {/* User Menu, Bookmark button, then Notification button */}
        <div className={`top-controls ${layout} ${isCollapsed ? 'hidden' : ''}`}>
          <UserMenu
            isOpen={isUserMenuOpen}
            onToggle={onUserMenuToggle}
          />
          <BookmarkButton
            onLibraryToggle={onLibraryToggle}
            isLibraryOpen={isLibraryOpen}
            bookmarkCount={bookmarkCount}
          />
          <NotificationButton
            onSidebarToggle={onNotificationSidebarToggle}
            isSidebarOpen={isNotificationSidebarOpen}
          />
        </div>
      </div>
    </>
  );
};

export default TopControls;
