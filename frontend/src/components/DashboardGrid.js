import React, { useState } from 'react';
import { useDateRange } from '../contexts/DateRangeContext';
import CollapsibleCard from './CollapsibleCard';
import './DashboardGrid.css';

/**
 * Internal marker component. Wrap a child in <DashboardGrid.Featured> to make
 * it span the full grid width, sitting above the regular columns.
 *
 *   <DashboardGrid columns={2}>
 *     <DashboardGrid.Featured>
 *       <TopRelationshipPairs ... />
 *     </DashboardGrid.Featured>
 *     <OrganizationsSection />
 *     <DecisionsSection />
 *   </DashboardGrid>
 */
const DashboardGridFeatured = ({ children }) => children;

/**
 * DashboardGrid — A unified grid container for dashboard data sections.
 *
 * Each child section should be a self-contained component that manages its
 * own data loading. The grid provides uniform visual styling, scroll behavior,
 * and responsive layout.
 *
 * Wrap a child in <DashboardGrid.Featured> to make it span all columns.
 *
 * @param {ReactNode} header - Optional header content rendered at the top (e.g. DateRangeSelector).
 */
const DashboardGrid = ({
  children,
  columns = 3,
  className = '',
  header,
}) => {
  return (
    <div
      className={
        'dashboard-grid' +
        ` dashboard-grid--cols-${columns}` +
        (className ? ` ${className}` : '')
      }
    >
      {header && (
        <div className="dashboard-grid-header">
          {header}
        </div>
      )}

      <div className="dashboard-grid-content">
        {React.Children.map(children, (child) => {
          if (!child) return null;
          const isFeatured = child.type === DashboardGridFeatured;
          return (
            <div
              className={
                'dashboard-grid-section' +
                (isFeatured ? ' dashboard-grid-section--featured' : '')
              }
            >
              {child}
            </div>
          );
        })}
      </div>
    </div>
  );
};

// Attach Featured as a static property
DashboardGrid.Featured = DashboardGridFeatured;

/**
 * A standard section header with title and optional "See All" link.
 * Use this inside your section components for consistent headers.
 */
export const DashboardSectionHeader = ({
  title,
  onSeeAll,
  seeAllLabel = 'See All →',
  children, // extra controls (toggles, filters, etc.)
}) => {
  return (
    <div className="dashboard-section-header">
      <div className="dashboard-section-header-left">
        <h2 className="dashboard-section-title">{title}</h2>
      </div>
      <div className="dashboard-section-header-right">
        {children}
        {onSeeAll && (
          <button className="dashboard-see-all-button" onClick={onSeeAll}>
            {seeAllLabel}
          </button>
        )}
      </div>
    </div>
  );
};

/**
 * CollapsibleSection — Wraps a data-section with either a simple
 * DashboardSectionHeader (non-collapsible) or a CollapsibleCard
 * (collapsible).  Delegates collapse behaviour to CollapsibleCard, the
 * canonical collapsible container used everywhere else in the app.
 *
 *   <CollapsibleSection title="Most Active Organizations" onSeeAll={...} collapsible>
 *     <div>... content ...</div>
 *   </CollapsibleSection>
 */
export const CollapsibleSection = ({
  title,
  onSeeAll,
  seeAllLabel,
  collapsible = false,
  defaultCollapsed = false,
  className = '',
  children,
  headerChildren,
}) => {
  // Hooks must be called unconditionally (rules-of-hooks), even when
  // collapsible is false — we just ignore the state in that branch.
  const [open, setOpen] = useState(!defaultCollapsed);

  if (!collapsible) {
    const sectionClass = `data-section${className ? ` ${className}` : ''}`;
    return (
      <section className={sectionClass}>
        <DashboardSectionHeader
          title={title}
          onSeeAll={onSeeAll}
          seeAllLabel={seeAllLabel}
        >
          {headerChildren}
        </DashboardSectionHeader>
        <div className="dashboard-section-collapse-body">
          {children}
        </div>
      </section>
    );
  }

  // Collapsible path: CollapsibleCard owns all visual styling.
  // Do NOT append "data-section" — it conflicts with the card's own chrome.
  // Use tag="div" instead of "details" so the card properly constrains
  // its children inside a flex/grid layout (<details> has browser bugs here).
  const cardClass = className || '';

  return (
    <CollapsibleCard
      title={title}
      badge={
        open && onSeeAll ? (
          <button className="dashboard-see-all-button" onClick={onSeeAll}>
            {seeAllLabel || 'See All →'}
          </button>
        ) : undefined
      }
      open={open}
      onToggle={setOpen}
      className={cardClass}
      tag="div"
    >
      {headerChildren}
      <div className="dashboard-section-collapse-body">
        {children}
      </div>
    </CollapsibleCard>
  );
};

/**
 * A loading skeleton for a dashboard grid section.
 */
export const DashboardSectionLoading = ({ message = 'Loading...' }) => {
  return (
    <div className="dashboard-section-loading">
      <div className="loading-spinner" />
      <p>{message}</p>
    </div>
  );
};

/**
 * Hook that components inside DashboardGrid can use to get the date range.
 * Re-exports useDateRange for convenience; components can also import it directly.
 */
export { useDateRange };

export default DashboardGrid;
