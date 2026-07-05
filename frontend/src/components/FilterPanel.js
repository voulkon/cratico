import React, { useState } from 'react';
import { Filter } from 'lucide-react';
import './FilterPanel.css';

/**
 * Filter panel.
 *
 * By default the panel is collapsible (clickable header toggles body).
 * Pass `nonCollapsible` to render an always-open panel with no toggle —
 * used when FilterPanel is nested inside DecisionsToolbar (which is itself
 * a <details>), to avoid nested collapsibles.
 */
const FilterPanel = ({
  activeFiltersCount,
  onClearAll,
  children,
  filterLabel = 'Filters',
  initiallyOpen = false,
  nonCollapsible = false,
}) => {
  const [open, setOpen] = useState(initiallyOpen);

  if (nonCollapsible) {
    return (
      <div className="filters-section">
        <div className="filters-header">
          <div className="filter-toggle-content">
            <Filter size={18} />
            <span>
              {filterLabel}
              {activeFiltersCount > 0 && ` (${activeFiltersCount})`}
            </span>
          </div>

          {activeFiltersCount > 0 && (
            <button
              className="clear-filters-button"
              onClick={(e) => {
                e.stopPropagation();
                onClearAll();
              }}
            >
              Clear All
            </button>
          )}
        </div>

        <div className="filters-panel">
          {children}
        </div>
      </div>
    );
  }

  return (
    <div className="filters-section">
      <div
        className="filters-header clickable"
        onClick={() => setOpen(!open)}
      >
        <div className="filter-toggle-content">
          <Filter size={18} />
          <span>
            {filterLabel}
            {activeFiltersCount > 0 && ` (${activeFiltersCount})`}
          </span>
          <span className="toggle-arrow">{open ? '▲' : '▼'}</span>
        </div>

        {activeFiltersCount > 0 && (
          <button
            className="clear-filters-button"
            onClick={(e) => {
              e.stopPropagation();
              onClearAll();
            }}
          >
            Clear All
          </button>
        )}
      </div>

      {open && (
        <div className="filters-panel">
          {children}
        </div>
      )}
    </div>
  );
};

export default FilterPanel;
