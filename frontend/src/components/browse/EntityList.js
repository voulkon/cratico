import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchBrowseEntities } from '../../api/browseApi';
import useInfiniteScroll from '../../hooks/useInfiniteScroll';
import {
  OrganizationIcon,
  UserIcon,
  UnitIcon,
  CompanyIcon,
  PenIcon,
} from '../Icons';
import './EntityList.css';

// ── Icon mapping ─────────────────────────────────────────────────
const TYPE_ICONS = {
  organization: <OrganizationIcon size={16} />,
  signer: <PenIcon size={16} />,
  unit: <UnitIcon size={16} />,
  company: <CompanyIcon size={16} />,
  company_person: <UserIcon size={16} />,
  afm_entity: <CompanyIcon size={16} />,
};

// ── Navigation per type ──────────────────────────────────────────
function getEntityUrl(item) {
  switch (item.type) {
    case 'organization':
      return `/entity/organization/${item.id}`;
    case 'signer':
      return `/entity/signer/${item.id}`;
    case 'unit':
      return `/entity/unit/${item.id}`;
    case 'company':
    case 'afm_entity':
      return `/entity/afm/${item.id}`;
    case 'company_person':
      return `/person/${encodeURIComponent(item.text)}`;
    default:
      return '#';
  }
}

// ── Derive display first letter from sort_key or text ─────────────
function getFirstLetter(item) {
  const key = item.sort_key || item.text || '';
  return key.charAt(0).toUpperCase() || '?';
}

// ── Component ────────────────────────────────────────────────────

/**
 * EntityList — alphabetical entity list with infinite scroll,
 * letter-grouped sticky headers, and optional prefix search.
 *
 * When a prefix query is active, performs progressive criteria
 * relaxation: first searches with the current letter + type filters,
 * then drops the letter filter, then drops the type filter —
 * accumulating results from each phase so exact matches appear first
 * and broader matches appear below a divider.
 *
 * Props:
 *   entityType  - 'all' | 'organization' | 'signer' | 'unit' |
 *                 'company' | 'companyperson' | 'afmentity'
 *   letter      - first-letter filter (optional)
 *   query       - free-text prefix filter (optional)
 *   sort        - 'asc' | 'desc'
 *   onLettersLoaded - callback(letters[]) — inform parent of available letters
 *   onLoadingChange - callback(bool) — inform parent when search is in progress
 *   scrollToLetter  - string | null — when set, scroll to this letter's heading
 */
const EntityList = ({
  entityType = 'all',
  letter = null,
  query = null,
  sort = 'asc',
  onLettersLoaded,
  onLoadingChange,
  scrollToLetter,
}) => {
  const navigate = useNavigate();

  // sections: array of { key, label, items, hasMore, offset, phase }
  // Each section represents one progressive-search phase's results.
  const [sections, setSections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  const abortControllerRef = useRef(null);
  const debounceTimerRef = useRef(null);
  const sectionsRef = useRef([]);
  const requestIdRef = useRef(0);

  // Keep sectionsRef in sync for pagination
  useEffect(() => {
    sectionsRef.current = sections;
  }, [sections]);

  // Notify parent of loading state (for search-input spinner)
  useEffect(() => {
    onLoadingChange?.(loading);
  }, [loading, onLoadingChange]);

  // ── Build progressive search phases ────────────────────────────
  // When a prefix query is active, we search in widening circles:
  //   Phase 1: current type + letter + query  (most specific)
  //   Phase 2: current type + query           (drop letter)
  //   Phase 3: all types + query              (drop type filter)
  // Results from each phase are accumulated so the user sees exact
  // matches first, then broader matches below a divider.
  const buildPhases = useCallback((q) => {
    if (!q || !q.trim()) return null;
    const trimmed = q.trim();
    const phases = [{ type: entityType, letter, query: trimmed, label: null }];
    if (letter) {
      phases.push({
        type: entityType,
        letter: null,
        query: trimmed,
        label: 'Results without letter filter',
      });
    }
    if (entityType !== 'all') {
      phases.push({
        type: 'all',
        letter: null,
        query: trimmed,
        label: 'Results from all categories',
      });
    }
    return phases;
  }, [entityType, letter]);

  // ── Fetch a single phase page ─────────────────────────────────
  const fetchPhasePage = useCallback(
    async (phase, offset, limit, signal) => {
      const params = { type: phase.type, sort, offset, limit };
      if (phase.letter) params.letter = phase.letter;
      if (phase.query) params.q = phase.query;
      return await fetchBrowseEntities(params, signal);
    },
    [sort]
  );

  // ── Progressive initial search ────────────────────────────────
  const performSearch = useCallback(async () => {
    const myRequestId = ++requestIdRef.current;

    // Abort any in-flight request from a previous search
    if (abortControllerRef.current) abortControllerRef.current.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setLoading(true);
    setError(null);
    setSections([]);
    sectionsRef.current = [];

    const phases = buildPhases(query);

    // No query → simple single fetch (alphabetical browse)
    if (!phases) {
      try {
        const data = await fetchPhasePage(
          { type: entityType, letter, query: null },
          0,
          50,
          controller.signal
        );
        if (myRequestId !== requestIdRef.current) return;
        const newSections = [
          {
            key: 'main',
            label: null,
            items: data.results,
            hasMore: data.has_more,
            offset: data.results.length,
            phase: { type: entityType, letter, query: null },
          },
        ];
        setSections(newSections);
        sectionsRef.current = newSections;
        if (onLettersLoaded && data.available_letters) {
          onLettersLoaded(data.available_letters);
        }
      } catch (err) {
        if (myRequestId !== requestIdRef.current) return;
        if (err?.code !== 'ERR_CANCELED') {
          console.error('Browse fetch failed:', err);
          setError(err.message || 'Failed to load entities');
        }
      } finally {
        if (myRequestId === requestIdRef.current) setLoading(false);
      }
      return;
    }

    // Progressive: execute phases sequentially, accumulate results
    const newSections = [];
    let lettersNotified = false;

    for (let i = 0; i < phases.length; i++) {
      if (myRequestId !== requestIdRef.current) return;
      const phase = phases[i];

      try {
        const data = await fetchPhasePage(phase, 0, 50, controller.signal);
        if (myRequestId !== requestIdRef.current) return;

        // Notify parent of available letters (once, from first phase)
        if (!lettersNotified && onLettersLoaded && data.available_letters) {
          onLettersLoaded(data.available_letters);
          lettersNotified = true;
        }

        // Deduplicate against previously accumulated sections
        const existingIds = new Set();
        newSections.forEach((s) =>
          s.items.forEach((item) => existingIds.add(`${item.type}-${item.id}`))
        );
        const newItems = data.results.filter(
          (item) => !existingIds.has(`${item.type}-${item.id}`)
        );

        if (newItems.length > 0) {
          newSections.push({
            key: `phase-${i}`,
            label: phase.label,
            items: newItems,
            hasMore: data.has_more,
            offset: data.results.length,
            phase,
          });
          setSections([...newSections]);
          sectionsRef.current = newSections;
        }
      } catch (err) {
        if (myRequestId !== requestIdRef.current) return;
        if (err?.code !== 'ERR_CANCELED') {
          console.error('Browse fetch failed:', err);
          setError(err.message || 'Failed to load entities');
        }
        return;
      }
    }

    if (myRequestId === requestIdRef.current) setLoading(false);
  }, [entityType, letter, query, sort, buildPhases, fetchPhasePage, onLettersLoaded]);

  // ── Debounced search trigger ──────────────────────────────────
  // Debounce only when a query is present (keystroke-driven).
  // Filter changes (type/letter/sort) fire immediately.
  useEffect(() => {
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    if (abortControllerRef.current) abortControllerRef.current.abort();

    debounceTimerRef.current = setTimeout(() => {
      performSearch();
    }, query ? 300 : 0);

    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityType, letter, query, sort]);

  // ── Cleanup on unmount ────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) abortControllerRef.current.abort();
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, []);

  // ── Load more (paginate the last section with hasMore) ────────
  const handleLoadMore = useCallback(async () => {
    const currentSections = sectionsRef.current;
    // Find the last section that still has more results to load
    let targetIdx = -1;
    for (let i = currentSections.length - 1; i >= 0; i--) {
      if (currentSections[i].hasMore) {
        targetIdx = i;
        break;
      }
    }
    if (targetIdx === -1) return;

    const myRequestId = requestIdRef.current;
    const targetSection = currentSections[targetIdx];
    setLoadingMore(true);

    try {
      const data = await fetchPhasePage(
        targetSection.phase,
        targetSection.offset,
        50
      );
      // Discard if a new search started while we were loading
      if (myRequestId !== requestIdRef.current) return;

      // Deduplicate against ALL existing items
      const existingIds = new Set();
      currentSections.forEach((s) =>
        s.items.forEach((item) => existingIds.add(`${item.type}-${item.id}`))
      );
      const newItems = data.results.filter(
        (item) => !existingIds.has(`${item.type}-${item.id}`)
      );

      const updatedSections = [...currentSections];
      updatedSections[targetIdx] = {
        ...targetSection,
        items: [...targetSection.items, ...newItems],
        hasMore: data.has_more,
        offset: targetSection.offset + data.results.length,
      };
      setSections(updatedSections);
      sectionsRef.current = updatedSections;
    } catch (err) {
      if (err?.code !== 'ERR_CANCELED') {
        console.error('Load more failed:', err);
      }
    } finally {
      if (myRequestId === requestIdRef.current) setLoadingMore(false);
    }
  }, [fetchPhasePage]);

  // ── Derived state ─────────────────────────────────────────────
  const hasMore = useMemo(
    () => sections.some((s) => s.hasMore),
    [sections]
  );
  const totalItems = useMemo(
    () => sections.reduce((sum, s) => sum + s.items.length, 0),
    [sections]
  );

  const { sentinelRef } = useInfiniteScroll({
    hasMore,
    loading,
    loadingMore,
    onLoadMore: handleLoadMore,
    enabled: totalItems > 0,
  });

  // ── Group items by first letter (within a section) ─────────────
  const groupItems = useCallback((items) => {
    const g = [];
    let currentLetter = null;
    for (const item of items) {
      const fl = getFirstLetter(item);
      if (fl !== currentLetter) {
        currentLetter = fl;
        g.push({ letter: fl, items: [item] });
      } else {
        g[g.length - 1].items.push(item);
      }
    }
    return g;
  }, []);

  // ── Scroll to letter ───────────────────────────────────────────
  useEffect(() => {
    if (!scrollToLetter || totalItems === 0) return;

    const el = document.querySelector(
      `[data-letter-heading="${scrollToLetter}"]`
    );
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [scrollToLetter, totalItems]);

  // ── Render helpers ─────────────────────────────────────────────
  const renderSkeleton = () => (
    <div className="entity-list-skeleton">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="entity-list-skeleton-row">
          <div className="skeleton-icon" />
          <div className="skeleton-text">
            <div className="skeleton-line skeleton-line--long" />
            <div className="skeleton-line skeleton-line--short" />
          </div>
        </div>
      ))}
    </div>
  );

  // ── Main render ────────────────────────────────────────────────
  if (loading && totalItems === 0) {
    return <div className="entity-list">{renderSkeleton()}</div>;
  }

  if (error && totalItems === 0) {
    return (
      <div className="entity-list entity-list--error">
        <div className="entity-list-error">
          <p>{error}</p>
          <button
            className="entity-list-retry-btn"
            onClick={() => performSearch()}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!loading && totalItems === 0) {
    return (
      <div className="entity-list entity-list--empty">
        <div className="entity-list-empty">
          <p>No entities found</p>
          {query && (
            <p className="entity-list-empty-hint">
              Try a different search term or clear the filter.
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="entity-list">
      {sections.map((section) => {
        const groups = groupItems(section.items);
        return (
          <div key={section.key} className="entity-list-section">
            {section.label && (
              <div className="entity-list-section-divider">
                {section.label}
              </div>
            )}
            {groups.map((group) => (
              <div key={group.letter} className="entity-list-group">
                <div
                  className="entity-list-letter-header"
                  data-letter-heading={group.letter}
                >
                  {group.letter}
                </div>
                {group.items.map((item) => (
                  <div
                    key={`${item.type}-${item.id}`}
                    className="entity-list-row"
                    onClick={() => navigate(getEntityUrl(item))}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') navigate(getEntityUrl(item));
                    }}
                  >
                    <span className="entity-list-row-icon">
                      {TYPE_ICONS[item.type] || <CompanyIcon size={16} />}
                    </span>
                    <span className="entity-list-row-text">{item.text}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        );
      })}

      {/* "Searching more broadly…" indicator */}
      {loading && totalItems > 0 && (
        <div className="entity-list-broadening">
          <div className="entity-list-spinner" />
          <span>Searching more broadly…</span>
        </div>
      )}

      {/* Infinite scroll sentinel */}
      <div ref={sentinelRef} className="entity-list-sentinel" />

      {loadingMore && (
        <div className="entity-list-loading-more">
          <div className="entity-list-spinner" />
          <span>Loading more…</span>
        </div>
      )}

      {!hasMore && !loading && totalItems > 0 && (
        <div className="entity-list-end">— End of results —</div>
      )}
    </div>
  );
};

export default EntityList;
