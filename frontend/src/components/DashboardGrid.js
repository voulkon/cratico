import React from 'react';
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
 */
const DashboardGrid = ({ children, columns = 3, className = '' }) => {
  return (
    <div
      className={`dashboard-grid dashboard-grid--cols-${columns} ${className}`}
    >
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
      <h2 className="dashboard-section-title">{title}</h2>
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
