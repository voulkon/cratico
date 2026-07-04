import React from 'react';
import './Chevron.css';

/**
 * Shared chevron icon (V-shaped SVG) used across all collapsible sections.
 *
 * Only ONE chevron implementation should exist in the codebase — import this
 * component instead of inlining an SVG.  It intentionally carries NO
 * positioning rules (absolute / flex / margins) so the parent can decide how
 * to place it.
 *
 * Props:
 *   open      – when true, the chevron points up (rotated 180°)
 *   className – forwarded to the <svg> for parent-specific positioning
 *   size      – width & height in px (default 16)
 */
const Chevron = ({ open = false, className = '', size = 16 }) => (
  <svg
    className={`crati-chevron${open ? ' crati-chevron--open' : ''} ${className}`.trim()}
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M4 6l4 4 4-4" />
  </svg>
);

export default Chevron;
