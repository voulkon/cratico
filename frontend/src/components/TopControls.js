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
      {/* Left side: page-header slot — stays fixed at top-left.
          The container is always rendered so the portal target (#top-bar-slot)
          is available even on the homepage. */}
      <div className={`left-controls ${isLibraryOpen ? 'shifted' : ''} ${isCollapsed ? 'controls-collapsed' : ''}`}>
        <div id="top-bar-slot" />
      </div>

      {/* Right side: Collapsible controls — lives inside the grid's .controls-area */}
      <div className={`top-controls-wrapper ${layout}`}>
        {/* Logo — always visible, sits at the top */}
        {!hideLogo && (
          <Logo size="small" />
        )}

        {/* Collapse/Expand Toggle — always visible, right below the logo */}
        <button
          className="controls-collapse-toggle"
          onClick={toggleCollapse}
          aria-label={isCollapsed ? 'Expand controls' : 'Collapse controls'}
          title={isCollapsed ? 'Expand controls' : 'Collapse controls'}
        >
          {isCollapsed ? <ChevronLeft size={20} /> : <ChevronRight size={20} />}
        </button>

        {/* Collapsible section: slides right and hides when collapsed */}
        <div className={`top-controls-collapsible ${isCollapsed ? 'collapsed' : 'expanded'}`}>
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
      </div>
    </>
  );
};

export default TopControls;
