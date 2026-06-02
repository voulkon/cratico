import React, { useState } from 'react';
import { Filter } from 'lucide-react';
import './FilterPanel.css';

const FilterPanel = ({
  activeFiltersCount,
  onClearAll,
  children,
  filterLabel = 'Filters',
  initiallyOpen = false,
}) => {
  const [open, setOpen] = useState(initiallyOpen);

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
