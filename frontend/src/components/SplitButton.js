import React from 'react';
import { ChevronUp, ChevronDown } from './Icons';
import './SplitButton.css';

/**
 * Reusable split button component with consistent behavior across the app.
 *
 * Features:
 * - Split button layout (main action + chevron toggle)
 * - Consistent hover and active states
 * - Customizable styling via className
 *
 * Note: Overlay is now managed centrally at the App level for consistent behavior.
 *
 * @param {Object} props
 * @param {React.ReactNode} props.children - Content for the main (left) button
 * @param {boolean} props.isOpen - Whether the associated content is open
 * @param {Function} props.onMainClick - Handler for main button click
 * @param {Function} props.onChevronClick - Handler for chevron button click
 * @param {boolean} props.mainActive - Whether main button should show active state
 * @param {string} props.mainClassName - Additional classes for main button
 * @param {string} props.chevronClassName - Additional classes for chevron button
 * @param {string} props.className - Additional classes for wrapper
 * @param {string} props.mainTitle - Tooltip for main button
 * @param {string} props.chevronTitle - Tooltip for chevron button
 * @param {boolean} props.disabled - Whether buttons are disabled (applies to both if mainDisabled/chevronDisabled not specified)
 * @param {boolean} props.mainDisabled - Whether main button is disabled (overrides disabled prop)
 * @param {boolean} props.chevronDisabled - Whether chevron button is disabled (overrides disabled prop)
 * @param {number} props.height - Button height in pixels (default: 50)
 * @param {React.ReactNode} props.badge - Optional badge to display on chevron button (e.g., unread count)
 */
export default function SplitButton({
  children,
  isOpen = false,
  onMainClick,
  onChevronClick,
  mainActive = false,
  mainClassName = '',
  chevronClassName = '',
  className = '',
  mainTitle = '',
  chevronTitle = '',
  disabled = false,
  mainDisabled,
  chevronDisabled,
  height = 50,
  badge = null,
}) {
  // Allow individual disabled states, or use the general disabled prop
  const isMainDisabled = mainDisabled !== undefined ? mainDisabled : disabled;
  const isChevronDisabled = chevronDisabled !== undefined ? chevronDisabled : disabled;

  return (
    <>
      {/* Split button wrapper */}
      <div className={`split-button ${isOpen ? 'split-button-open' : ''} ${className}`}>
        {/* Main action button (left half) */}
        <button
          className={`split-button-main ${mainActive ? 'active' : ''} ${mainClassName}`}
          onClick={onMainClick}
          disabled={isMainDisabled}
          title={mainTitle}
          style={{ height: `${height}px` }}
        >
          {children}
        </button>

        {/* Chevron toggle button (right half) */}
        <button
          className={`split-button-chevron ${isOpen ? 'active' : ''} ${chevronClassName}`}
          onClick={onChevronClick}
          disabled={isChevronDisabled}
          title={chevronTitle || (isOpen ? 'Close' : 'Open')}
          style={{ height: `${height}px` }}
        >
          <span className="split-button-chevron-icon">
            {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </span>
          {badge && <div className="split-button-badge">{badge}</div>}
        </button>
      </div>
    </>
  );
}
