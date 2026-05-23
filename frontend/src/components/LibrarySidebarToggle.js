import React from 'react'
import './LibrarySidebarToggle.css'
import {LibraryToggleIcon} from './Icons.js';

/**
 * Toggle button for Library sidebar (like ChatGPT/Claude)
 * Shows in TopControls
 */
export default function LibrarySidebarToggle({ isOpen, onToggle, bookmarkCount }) {
  return (
    <button
      className={`library-toggle ${isOpen ? 'active' : ''}`}
      onClick={onToggle}
      title={isOpen ? 'Close Library' : 'Open Library'}
    >
      <span className="library-icon"><LibraryToggleIcon /></span>
      {bookmarkCount > 0 && (
        <span className="library-badge">{bookmarkCount}</span>
      )}
    </button>
  );
}
