import React from 'react';
import { useTranslation } from '../contexts/TranslationContext';
import SortControl from './SortControl';
import SearchInput from './SearchInput';
import FilterPanel from './FilterPanel';
import CollapsibleCard from './CollapsibleCard';
import './DecisionsToolbar.css';

/**
 * Unified toolbar for the "decisions" section of every detail page.
 *
 * Combines: title + count, optional search, optional direct-only toggle,
 * optional viewed-filter dropdown (for notification pages), sort, and a
 * collapsible filter panel (amount range + decision-type checkboxes — both
 * conditionally rendered), plus active-filter chips and "showing X–Y of Z".
 *
 * Replaces per-page inline markup in EntityDetailPage,
 * RelationshipDetailPage, AFMEntityDetailPage, NotificationBatchDetailPage,
 * and SubscriptionHistoryPage.
 *
 * Collapsible: the entire toolbar collapses into a single summary row.
 *
 * Open/closed state: the toolbar leans on the native <details>/<summary>
 * element for open/close behavior. To avoid a feedback loop (mirrored state
 * fighting the browser's own toggle), we do NOT keep a parallel `isOpen`
 * state that drives the `open` attribute. Instead:
 *   - Uncontrolled (default): <details> manages itself; we only track
 *     `open` for the chevron rotation via the `onToggle` event.
 *   - Controlled: caller passes `open` + `onToggle`; we forward `onToggle`
 *     and never mutate `open` ourselves.
 */
const DecisionsToolbar = ({
  // Title row
  title,
  totalCount,
  // Search
  searchQuery,
  onSearchChange,
  searchPlaceholder,
  // Direct-only toggle
  directOnly,
  onDirectOnlyChange,
  // Viewed filter (notification pages — null=all, true=viewed, false=unviewed)
  viewedFilter,
  onViewedFilterChange,
  // Sort
  sortBy,
  onSortChange,
  sortVariant = 'simple', // 'simple' (2 options, default) | 'full' (4 options) | array
  // Filter panel
  activeFiltersCount,
  onClearAll,
  filterLabel,
  // Amount filters (rendered only when onAmountChange is provided)
  amountFilters,
  onAmountChange,
  // Decision-type filters (rendered only when onTypeToggle + decisionTypes are provided)
  decisionTypes,
  selectedTypes,
  onTypeToggle,
  typesLoading,
  // Results info
  pagination,
  // Optional extra content inside the filter panel (e.g. org filters)
  extraFilters,
  // Optional children rendered inside the collapsible body — typically <DecisionList>
  children,
  // Collapsible state
  open: controlledOpen,
  onToggle,
  defaultOpen = true,
}) => {
  const { t } = useTranslation();

  const total = totalCount ?? pagination?.total_count ?? pagination?.total_items ?? 0;

  // Resolve "showing X–Y of Z" range from pagination
  const showingStart = pagination
    ? ((pagination.current_page - 1) * pagination.page_size) + 1
    : 0;
  const showingEnd = pagination
    ? Math.min(pagination.current_page * pagination.page_size, total)
    : 0;

  // ── Effective filter count (includes the viewed-filter and search query) ──
  const hasViewedFilter = viewedFilter !== null && viewedFilter !== undefined;
  const showSearch = typeof onSearchChange === 'function';
  const showDirectOnly = typeof onDirectOnlyChange === 'function';
  const showAmountFilters = typeof onAmountChange === 'function';
  const showDecisionTypes = typeof onTypeToggle === 'function' && decisionTypes != null;
  const hasFilterPanel = showAmountFilters || showDecisionTypes || extraFilters;
  const hasSearchQuery = !!(searchQuery && searchQuery.trim());
  const effectiveFilterCount =
    (activeFiltersCount ?? 0) + (hasViewedFilter ? 1 : 0) + (hasSearchQuery ? 1 : 0);

  // ── Resolve viewed filter label (i18n) ──
  const viewedFilterLabel = viewedFilter === true
    ? t('decisionsToolbar.viewedOnly', 'Viewed Only')
    : viewedFilter === false
      ? t('decisionsToolbar.unviewedOnly', 'Unviewed Only')
      : null;

  // ── Build subtitle (count + filter badge) ──────────────────────
  const subtitle = (
    <>
      {total > 0 && <>({total.toLocaleString()})</>}
      {effectiveFilterCount > 0 && <> ({effectiveFilterCount})</>}
    </>
  );

  return (
    <CollapsibleCard
      title={title}
      subtitle={subtitle}
      open={controlledOpen}
      onToggle={onToggle}
      defaultOpen={defaultOpen}
      className="decisions-toolbar"
    >
      <div className="decisions-toolbar-content">
      <div className="decisions-toolbar-header">
        <div className="decisions-toolbar-controls">
          {showSearch && (
            <SearchInput
              value={searchQuery}
              onChange={onSearchChange}
              placeholder={searchPlaceholder || t('entityDetail.searchInDecisions')}
              label={`${t('entityDetail.search')}:`}
            />
          )}

          {showDirectOnly && (
            <label className="decisions-toolbar-checkbox">
              <input
                type="checkbox"
                checked={directOnly}
                onChange={(e) => onDirectOnlyChange(e.target.checked)}
              />
              <span>{t('filters.directAssignmentsOnly', 'Direct Assignments Only')}</span>
            </label>
          )}

          {/* Viewed filter — for notification batch / subscription pages */}
          {typeof onViewedFilterChange === 'function' && (
            <div className="decisions-toolbar-viewed-filter">
              <label htmlFor="toolbar-viewed-filter" className="sort-label">
                {t('decisionsToolbar.filterLabel', 'Filter:')}
              </label>
              <select
                id="toolbar-viewed-filter"
                className="sort-select"
                value={viewedFilter === null ? 'all' : String(viewedFilter)}
                onChange={(e) => {
                  const value = e.target.value;
                  onViewedFilterChange(value === 'all' ? null : value === 'true');
                }}
              >
                <option value="all">{t('decisionsToolbar.allDecisions', 'All Decisions')}</option>
                <option value="false">{t('decisionsToolbar.unviewedOnly', 'Unviewed Only')}</option>
                <option value="true">{t('decisionsToolbar.viewedOnly', 'Viewed Only')}</option>
              </select>
            </div>
          )}

          <SortControl
            sortBy={sortBy}
            onSortChange={onSortChange}
            options={sortVariant}
          />
        </div>
      </div>

      {hasFilterPanel && (
        <FilterPanel
          activeFiltersCount={activeFiltersCount}
          onClearAll={onClearAll}
          filterLabel={filterLabel || t('entityDetail.filters')}
        >
          {/* Amount Filters */}
          {showAmountFilters && (
            <div className="filter-group">
              <h4>{t('entityDetail.amountRange')}</h4>
              <div className="amount-filters">
                <input
                  type="number"
                  placeholder={t('entityDetail.minAmountPlaceholder')}
                  value={amountFilters.minAmount}
                  onChange={(e) => onAmountChange('minAmount', e.target.value)}
                  className="amount-input"
                />
                <span className="amount-separator">{t('entityDetail.amountTo')}</span>
                <input
                  type="number"
                  placeholder={t('entityDetail.maxAmountPlaceholder')}
                  value={amountFilters.maxAmount}
                  onChange={(e) => onAmountChange('maxAmount', e.target.value)}
                  className="amount-input"
                />
              </div>
            </div>
          )}

          {/* Decision Type Filters */}
          {showDecisionTypes && (
            <div className="filter-group">
              <h4>{t('entityDetail.decisionTypes')}</h4>
              {typesLoading ? (
                <div className="loading-text">{t('entityDetail.loadingDecisionTypes')}</div>
              ) : decisionTypes.length === 0 ? (
                <div className="loading-text">{t('entityDetail.noDecisionTypes', 'No decision types in this range')}</div>
              ) : (
                <div className="decision-types-grid">
                  {decisionTypes.map(type => (
                    <label key={type.uid} className="decision-type-checkbox">
                      <input
                        type="checkbox"
                        checked={selectedTypes.includes(type.uid)}
                        onChange={(e) => onTypeToggle(type.uid, e.target.checked)}
                      />
                      <span className="checkbox-content">
                        <span className="type-label">{type.label}</span>
                        <span className="type-stats">
                          {t('entityDetail.decisionTypesCount', {
                            count: type.count,
                            amount: (type.total_amount || 0).toLocaleString()
                          })}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Page-specific extra filters (e.g. organization filters in temporal mode) */}
          {extraFilters}
        </FilterPanel>
      )}

      {/* Search results info */}
      {searchQuery && showSearch && (
        <div className="search-results-info">
          <span className="search-results-bold">
            {t('entityDetail.searchResultsFor')} "{searchQuery}"
          </span>
          {pagination && (
            <span className="search-results-count">
              {t('entityDetail.resultsFound', { count: total })}
            </span>
          )}
        </div>
      )}

      {/* Active filter chips */}
      {effectiveFilterCount > 0 && (
        <div className="active-filters">
          <span className="filters-label">{t('entityDetail.activeFilters')}</span>

          {/* Search-query chip */}
          {hasSearchQuery && showSearch && (
            <span className="filter-tag">
              {t('entityDetail.searchResultsFor')} "{searchQuery}"
              <button onClick={() => onSearchChange('')}>×</button>
            </span>
          )}

          {/* Viewed-filter chip */}
          {hasViewedFilter && (
            <span className="filter-tag">
              {viewedFilterLabel}
              <button onClick={() => onViewedFilterChange(null)}>×</button>
            </span>
          )}

          {selectedTypes && selectedTypes.map(typeUid => {
            const type = decisionTypes?.find(dt => dt.uid === typeUid);
            return (
              <span key={typeUid} className="filter-tag">
                {type?.label || typeUid}
                <button onClick={() => onTypeToggle(typeUid, false)}>×</button>
              </span>
            );
          })}
          {amountFilters?.minAmount && (
            <span className="filter-tag">
              {t('entityDetail.minAmountFilter', { amount: amountFilters.minAmount })}
              <button onClick={() => onAmountChange('minAmount', '')}>×</button>
            </span>
          )}
          {amountFilters?.maxAmount && (
            <span className="filter-tag">
              {t('entityDetail.maxAmountFilter', { amount: amountFilters.maxAmount })}
              <button onClick={() => onAmountChange('maxAmount', '')}>×</button>
            </span>
          )}
        </div>
      )}

      {/* Showing X–Y of Z — this toolbar is the single owner of the
          "showing X–Y of Z" summary. DecisionList should be called with
          showPaginationInfo={false} (the default) when nested here, to
          avoid a duplicate pagination line. */}
      {pagination && total > 0 && (
        <div className="search-results-info">
          <span className="search-results-count">
            {t('common.showingResults', {
              start: showingStart,
              end: showingEnd,
              total
            })}
          </span>
        </div>
      )}

      {/* Children (typically <DecisionList>) — inside the collapsible body */}
      {children}
      </div>
    </CollapsibleCard>
  );
};

export default DecisionsToolbar;
