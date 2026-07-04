import React from 'react';
import './CategoryTabs.css';

/**
 * Reusable category tab bar.
 *
 * Each tab is defined by:
 *   { key: string, label: string, icon?: ReactNode, count: number,
 *     visible?: boolean, actionSlot?: ReactNode }
 *
 * The "All" tab should be the first entry and always visible.
 *
 * Usage:
 *   <CategoryTabs
 *     categories={[
 *       { key: 'all', label: 'All', count: 42 },
 *       { key: 'organizations', label: 'Organizations', icon: <OrgIcon />, count: 10 },
 *     ]}
 *     selectedKey={selected}
 *     onSelect={setSelected}
 *     className="my-custom-tabs"
 *   />
 */
const CategoryTabs = ({ categories, selectedKey, onSelect, className }) => {
  const visibleTabs = categories.filter(
    (c) => c.key === 'all' || c.visible === undefined || c.visible
  );

  if (visibleTabs.length <= 1) return null;

  return (
    <div className={`category-tabs${className ? ' ' + className : ''}`} role="tablist" aria-label="Browse categories">
      {visibleTabs.map((tab) => (
        <div key={tab.key} className="category-tab-wrapper">
          <button
            className={`category-tab ${selectedKey === tab.key ? 'active' : ''}`}
            onClick={() => onSelect(tab.key)}
            onMouseDown={(e) => e.preventDefault()}
            role="tab"
            aria-selected={selectedKey === tab.key}
          >
            {tab.icon && <span className="category-tab-icon">{tab.icon}</span>}
            <span className="category-tab-label">{tab.label}</span>
            {tab.count > 0 && <span className="category-tab-count">{tab.count}</span>}
          </button>
          {selectedKey === tab.key && tab.actionSlot && (
            <div className="category-tab-action">{tab.actionSlot}</div>
          )}
        </div>
      ))}
    </div>
  );
};

export default CategoryTabs;
