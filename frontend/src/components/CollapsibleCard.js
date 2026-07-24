import React, { useState } from 'react';
import Chevron from './Chevron';
import './CollapsibleCard.css';

/**
 * CollapsibleCard — a single, canonical collapsible <details> card.
 *
 * Centralizes the card shell, summary row, and chevron for every collapsible
 * section in the app.  Consumers only provide title/subtitle/badge/content.
 *
 * Visual spec (enforced here, not duplicated across consumers):
 *   • Borderless card with --card-shadow, hover lift (translateY(-2px))
 *   • Centered title in --text-color (not --palette-primary)
 *   • Optional left accent border (4px --palette-primary)
 *   • Chevron pinned absolute-right; optional badge sits left of it
 *   • Content divider (border-top) only visible when the card is open
 *
 * Props:
 *   title         – ReactNode for the main title
 *   subtitle      – ReactNode rendered after the title (counts, target names, …)
 *   badge         – ReactNode rendered right-side, before the chevron
 *   open          – controlled open state (omit for uncontrolled)
 *   onToggle      – (open: boolean) => void — controlled toggle handler
 *   defaultOpen   – initial open state when uncontrolled (default: true)
 *   accentBorder  – show 4px left accent border (default: false)
 *   className     – forwarded to the root element
 *   children      – collapsible body content
 *   tag           – "details" (default, native <details>) or "div"
 *                   Use "div" when the card sits inside a flex/grid
 *                   container that needs to constrain the card's height
 *                   (<details> doesn't reliably constrain its children).
 */
const CollapsibleCard = ({
  title,
  subtitle,
  badge,
  open: controlledOpen,
  onToggle,
  defaultOpen = true,
  accentBorder = false,
  className = '',
  children,
  tag = 'details',
}) => {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);

  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;

  const handleToggle = (e) => {
    // When tag="div" we manage state via click; when tag="details"
    // the browser fires onToggle with e.target.open.
    if (tag === 'div') {
      const next = !isOpen;
      if (isControlled) {
        onToggle?.(next);
      } else {
        setUncontrolledOpen(next);
      }
      return;
    }
    const next = e.target.open;
    if (isControlled) {
      onToggle?.(next);
    } else {
      setUncontrolledOpen(next);
    }
  };

  const rootClass = [
    'collapsible-card',
    accentBorder ? 'collapsible-card--accent' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const summaryContent = (
    <>
      <span className="collapsible-card__title-group">
        <span className="collapsible-card__title">{title}</span>
        {subtitle && (
          <span className="collapsible-card__subtitle">{subtitle}</span>
        )}
      </span>

      <span className="collapsible-card__right">
        {badge}
        <Chevron open={isOpen} className="collapsible-card__chevron" />
      </span>
    </>
  );

  if (tag === 'div') {
    return (
      <div className={rootClass}>
        <div
          className="collapsible-card__summary"
          onClick={handleToggle}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              handleToggle();
            }
          }}
        >
          {summaryContent}
        </div>
        {isOpen && (
          <div className="collapsible-card__content">{children}</div>
        )}
      </div>
    );
  }

  return (
    <details className={rootClass} open={isOpen} onToggle={handleToggle}>
      <summary className="collapsible-card__summary">
        {summaryContent}
      </summary>

      <div className="collapsible-card__content">{children}</div>
    </details>
  );
};

export default CollapsibleCard;
