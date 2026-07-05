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
 *   className     – forwarded to the root <details> element
 *   children      – collapsible body content
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
}) => {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);

  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;

  const handleToggle = (e) => {
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

  return (
    <details className={rootClass} open={isOpen} onToggle={handleToggle}>
      <summary className="collapsible-card__summary">
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
      </summary>

      <div className="collapsible-card__content">{children}</div>
    </details>
  );
};

export default CollapsibleCard;
