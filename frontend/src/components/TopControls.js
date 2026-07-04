import React from 'react';
import Logo from './Logo';
import UserMenu from './UserMenu';
import BookmarkButton from './BookmarkButton';
import NotificationButton from './NotificationButton';
import FontSizeControl from './FontSizeControl';
import { ChevronRight, ChevronLeft } from './Icons';
import './TopControls.css';

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
 * @param {boolean} isCollapsed - Whether the controls column is collapsed
 * @param {function} onToggleCollapse - Toggle callback for collapse/expand
 */
const TopControls = ({
  layout = 'vertical-right',
  onLibraryToggle,
  isLibraryOpen,
  bookmarkCount,
  onNotificationSidebarToggle,
  isNotificationSidebarOpen,
  onUserMenuToggle,
  isUserMenuOpen,
  hideLogo = false,
  isCollapsed = false,
  onToggleCollapse
}) => {
  const toggleCollapse = () => {
    onToggleCollapse();
  };

  return (
    <>
      {/* Left side: Logo (conditionally rendered) — stays fixed at top-left */}
      {!hideLogo && (
        <div className={`left-controls ${isLibraryOpen ? 'shifted' : ''}`}>
          <div className="logo-container">
            <Logo size="small" />
          </div>
        </div>
      )}

      {/* Right side: Collapsible controls — lives inside the grid's .controls-area */}
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
        <div className={`top-controls ${layout}`}>
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
          <FontSizeControl />
        </div>
      </div>
    </>
  );
};

export default TopControls;
