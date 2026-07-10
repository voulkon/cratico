import React, { useState, useEffect, useCallback } from 'react';
import { Filter } from 'lucide-react';
import { useTranslation } from '../contexts/TranslationContext';
import './FilterPanel.css';

/**
 * Filter panel with draft-state buffering.
 *
 * Amount inputs and decision-type checkboxes are rendered internally with
 * local draft state.  Changes are NOT propagated to the parent until the
 * user clicks "Apply".  This prevents a request storm when typing a
 * multi-digit number or toggling several checkboxes in a row.
 *
 * Extra page-specific filters can still be passed as `children`; they
 * render below the built-in filters and are NOT buffered.
 *
 * By default the panel is collapsible (clickable header toggles body).
 * Pass `nonCollapsible` to render an always-open panel with no toggle.
 */
const FilterPanel = ({
  // ── Header / chrome ────────────────────────────────────────────────
  activeFiltersCount,
  onClearAll,
  children,
  filterLabel = 'Filters',
  initiallyOpen = false,
  nonCollapsible = false,

  // ── Amount filters (buffered) ──────────────────────────────────────
  amountFilters,
  // ── Decision-type filters (buffered) ───────────────────────────────
  decisionTypes,
  selectedTypes,
  typesLoading,
  // ── Unified apply callback ─────────────────────────────────────────
  // Called with { amountFilters?: {minAmount, maxAmount}, selectedTypes?: string[] }
  // when the user clicks "Apply".  Using a single callback avoids a race
  // between two sequential setSearchParams calls (React 18 batches state
  // but each updateUrl reads the *current* closure, so the second call
  // would see stale values from before the first).
  onApply,
}) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(initiallyOpen);

  // ── Draft state — mirrors the *applied* values until the user edits ──
  const [draftMinAmount, setDraftMinAmount] = useState(amountFilters?.minAmount ?? '');
  const [draftMaxAmount, setDraftMaxAmount] = useState(amountFilters?.maxAmount ?? '');
  const [draftTypes, setDraftTypes] = useState(selectedTypes ?? []);

  const showAmountFilters = !!(amountFilters !== undefined && typeof onApply === 'function');
  const showDecisionTypes = !!(decisionTypes != null && typeof onApply === 'function');

  // Keep draft in sync when applied values change externally
  // (e.g. URL navigation, Clear All).
  useEffect(() => {
    setDraftMinAmount(amountFilters?.minAmount ?? '');
    setDraftMaxAmount(amountFilters?.maxAmount ?? '');
  }, [amountFilters?.minAmount, amountFilters?.maxAmount]);

  useEffect(() => {
    setDraftTypes(selectedTypes ?? []);
  }, [selectedTypes]);

  // ── Derived: are there pending (unapplied) changes? ────────────────
  const hasPendingChanges = (() => {
    if (showAmountFilters) {
      const curMin = amountFilters?.minAmount ?? '';
      const curMax = amountFilters?.maxAmount ?? '';
      if (String(draftMinAmount ?? '') !== String(curMin)) return true;
      if (String(draftMaxAmount ?? '') !== String(curMax)) return true;
    }
    if (showDecisionTypes) {
      const cur = selectedTypes ?? [];
      const draft = draftTypes ?? [];
      if (cur.length !== draft.length) return true;
      const curSet = new Set(cur);
      if (draft.some((t) => !curSet.has(t))) return true;
    }
    return false;
  })();

  // ── Apply: flush draft → single parent callback ────────────────────
  const handleApply = useCallback(() => {
    const updates = {};
    if (showAmountFilters) {
      updates.amountFilters = { minAmount: draftMinAmount, maxAmount: draftMaxAmount };
    }
    if (showDecisionTypes) {
      updates.selectedTypes = draftTypes;
    }
    onApply(updates);
  }, [showAmountFilters, showDecisionTypes, draftMinAmount, draftMaxAmount, draftTypes, onApply]);

  // ── Reset: revert draft to currently-applied values ────────────────
  const handleReset = useCallback(() => {
    setDraftMinAmount(amountFilters?.minAmount ?? '');
    setDraftMaxAmount(amountFilters?.maxAmount ?? '');
    setDraftTypes(selectedTypes ?? []);
  }, [amountFilters, selectedTypes]);

  // ── Clear All (header button) — also reset draft ───────────────────
  const handleClearAll = useCallback((e) => {
    if (e) e.stopPropagation();
    setDraftMinAmount('');
    setDraftMaxAmount('');
    setDraftTypes([]);
    onClearAll();
  }, [onClearAll]);

  // ── Render ─────────────────────────────────────────────────────────
  const headerContent = (
    <div className="filter-toggle-content">
      <Filter size={18} />
      <span>
        {filterLabel}
        {activeFiltersCount > 0 && ` (${activeFiltersCount})`}
      </span>
      {!nonCollapsible && <span className="toggle-arrow">{open ? '▲' : '▼'}</span>}
    </div>
  );

  const clearAllButton = activeFiltersCount > 0 && (
    <button className="clear-filters-button" onClick={handleClearAll}>
      Clear All
    </button>
  );

  const applyButton = hasPendingChanges && (
    <button
      className="clear-filters-button"
      style={{ backgroundColor: 'var(--palette-primary)', marginRight: 'var(--spacing-xs)' }}
      onClick={(e) => { e.stopPropagation(); handleApply(); }}
    >
      {t('filterPanel.apply', 'Apply')}
    </button>
  );

  const resetButton = hasPendingChanges && (
    <button
      className="clear-filters-button"
      style={{ backgroundColor: 'var(--muted-text)' }}
      onClick={(e) => { e.stopPropagation(); handleReset(); }}
    >
      {t('filterPanel.reset', 'Reset')}
    </button>
  );

  const filterBody = (
    <div className="filters-panel">
      {/* ── Amount Filters ─────────────────────────────────────── */}
      {showAmountFilters && (
        <div className="filter-group">
          <h4>{t('entityDetail.amountRange')}</h4>
          <div className="amount-filters">
            <input
              type="number"
              placeholder={t('entityDetail.minAmountPlaceholder')}
              value={draftMinAmount}
              onChange={(e) => setDraftMinAmount(e.target.value)}
              className="amount-input"
            />
            <span className="amount-separator">{t('entityDetail.amountTo')}</span>
            <input
              type="number"
              placeholder={t('entityDetail.maxAmountPlaceholder')}
              value={draftMaxAmount}
              onChange={(e) => setDraftMaxAmount(e.target.value)}
              className="amount-input"
            />
          </div>
        </div>
      )}

      {/* ── Decision Type Filters ──────────────────────────────── */}
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
                    checked={draftTypes.includes(type.uid)}
                    onChange={(e) => {
                      setDraftTypes(prev =>
                        e.target.checked
                          ? [...prev, type.uid]
                          : prev.filter(t => t !== type.uid)
                      );
                    }}
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

      {/* ── Extra page-specific filters (unbuffered) ───────────── */}
      {children}
    </div>
  );

  // ── Non-collapsible variant ─────────────────────────────────────
  if (nonCollapsible) {
    return (
      <div className="filters-section">
        <div className="filters-header">
          {headerContent}
          {applyButton}
          {resetButton}
          {clearAllButton}
        </div>
        {filterBody}
      </div>
    );
  }

  // ── Collapsible variant (default) ───────────────────────────────
  return (
    <div className="filters-section">
      <div
        className="filters-header clickable"
        onClick={() => setOpen(!open)}
      >
        {headerContent}
        {applyButton}
        {resetButton}
        {clearAllButton}
      </div>
      {open && filterBody}
    </div>
  );
};

export default FilterPanel;
