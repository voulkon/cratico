import React, { useState, useCallback } from 'react';
import { useDateRange } from '../contexts/DateRangeContext';
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
 * @param {boolean}   collapsible     - If true, shows a collapse toggle in the top-right corner.
 * @param {boolean}   defaultCollapsed - Initial collapsed state (only when collapsible).
 * @param {ReactNode} header          - Optional header content rendered at the top (e.g. DateRangeSelector).
 */
const DashboardGrid = ({
  children,
  columns = 3,
  className = '',
  collapsible = false,
  defaultCollapsed = false,
  header,
}) => {
  const [gridCollapsed, setGridCollapsed] = useState(defaultCollapsed);

  const toggleGrid = useCallback(() => {
    setGridCollapsed((prev) => !prev);
  }, []);

  return (
    <div
      className={
        'dashboard-grid' +
        ` dashboard-grid--cols-${columns}` +
        (className ? ` ${className}` : '') +
        (collapsible ? ' dashboard-grid--collapsible' : '') +
        (gridCollapsed ? ' dashboard-grid--collapsed' : '')
      }
    >
      {collapsible && (
        <button
          className="dashboard-grid-collapse-toggle"
          onClick={toggleGrid}
          aria-expanded={!gridCollapsed}
          title={gridCollapsed ? 'Expand dashboard' : 'Collapse dashboard'}
        >
          <span
            className={`dashboard-collapse-chevron${gridCollapsed ? ' dashboard-collapse-chevron--collapsed' : ''}`}
            aria-hidden="true"
          />
        </button>
      )}

      {header && (
        <div className="dashboard-grid-header">
          {header}
        </div>
      )}

      {!gridCollapsed && (
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
      )}
    </div>
  );
};

// Attach Featured as a static property
DashboardGrid.Featured = DashboardGridFeatured;

/**
 * A standard section header with title and optional "See All" link.
 * Use this inside your section components for consistent headers.
 *
 * @param {boolean}  collapsible - If true, shows a collapse toggle button.
 * @param {boolean}  collapsed  - Current collapsed state (controlled).
 * @param {function} onToggle   - Callback when toggle is clicked.
 */
export const DashboardSectionHeader = ({
  title,
  onSeeAll,
  seeAllLabel = 'See All →',
  collapsible = false,
  collapsed = false,
  onToggle,
  children, // extra controls (toggles, filters, etc.)
}) => {
  return (
    <div className="dashboard-section-header">
      <div className="dashboard-section-header-left">
        {collapsible && (
          <button
            className="dashboard-section-collapse-toggle"
            onClick={onToggle}
            aria-expanded={!collapsed}
            title={collapsed ? 'Expand section' : 'Collapse section'}
          >
            <span
              className={`dashboard-collapse-chevron${collapsed ? ' dashboard-collapse-chevron--collapsed' : ''}`}
              aria-hidden="true"
            />
          </button>
        )}
        <h2 className="dashboard-section-title">{title}</h2>
      </div>
      <div className="dashboard-section-header-right">
        {children}
        {onSeeAll && !collapsed && (
          <button className="dashboard-see-all-button" onClick={onSeeAll}>
            {seeAllLabel}
          </button>
        )}
      </div>
    </div>
  );
};

/**
 * CollapsibleSection — Wraps a data-section with a DashboardSectionHeader
 * and manages its own collapse state. When collapsed, only the header is shown.
 *
 *   <CollapsibleSection title="Most Active Organizations" onSeeAll={...}>
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
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  const handleToggle = useCallback(() => {
    setCollapsed((prev) => !prev);
  }, []);

  return (
    <section className={`data-section${className ? ` ${className}` : ''}`}>
      <DashboardSectionHeader
        title={title}
        onSeeAll={collapsed ? undefined : onSeeAll}
        seeAllLabel={seeAllLabel}
        collapsible={collapsible}
        collapsed={collapsed}
        onToggle={handleToggle}
      >
        {headerChildren}
      </DashboardSectionHeader>
      {!collapsed && (
        <div className="dashboard-section-collapse-body">
          {children}
        </div>
      )}
    </section>
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
