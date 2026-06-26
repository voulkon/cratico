import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import CategoryTabs from '../components/CategoryTabs';
import LetterIndex from '../components/browse/LetterIndex';
import EntityList from '../components/browse/EntityList';
import {
  OrganizationIcon,
  UserIcon,
  UnitIcon,
  CompanyIcon,
  PenIcon,
  SearchIcon,
} from '../components/Icons';
import './BrowsePage.css';

// ── Category definitions ──────────────────────────────────────────
const ALL_KEY = 'all';

const CATEGORIES = [
  { key: ALL_KEY, label: 'All', icon: null },
  { key: 'organization', label: 'Organizations', icon: <OrganizationIcon size={14} /> },
  { key: 'signer', label: 'Signers', icon: <PenIcon size={14} /> },
  { key: 'unit', label: 'Units', icon: <UnitIcon size={14} /> },
  { key: 'company', label: 'Companies', icon: <CompanyIcon size={14} /> },
  { key: 'companyperson', label: 'People', icon: <UserIcon size={14} /> },
  { key: 'afmentity', label: 'AFM Entities', icon: <CompanyIcon size={14} /> },
];

// ── Component ────────────────────────────────────────────────────

const BrowsePage = () => {
  const [searchParams, setSearchParams] = useSearchParams();

  // Read state from URL (bookmarkable + back-button friendly)
  const entityType = searchParams.get('type') || ALL_KEY;
  const letter = searchParams.get('letter') || null;
  const sort = searchParams.get('sort') || 'asc';

  // Local state
  const [prefixQuery, setPrefixQuery] = useState('');
  const [availableLetters, setAvailableLetters] = useState([]);
  const [scrollToLetter, setScrollToLetter] = useState(null);

  const scrollContainerRef = useRef(null);
  const searchInputRef = useRef(null);

  // ── Update URL when filters change ─────────────────────────────
  const updateParam = useCallback(
    (key, value) => {
      const next = new URLSearchParams(searchParams);
      if (value && value !== ALL_KEY) {
        next.set(key, value);
      } else {
        next.delete(key);
      }
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const handleTypeChange = useCallback(
    (key) => {
      updateParam('type', key);
    },
    [updateParam]
  );

  const handleSortToggle = useCallback(() => {
    updateParam('sort', sort === 'asc' ? 'desc' : 'asc');
  }, [sort, updateParam]);

  // ── Letter click from sidebar ──────────────────────────────────
  const handleLetterClick = useCallback(
    (clickedLetter) => {
      // If we already have results for this letter, just scroll
      if (availableLetters.includes(clickedLetter)) {
        setScrollToLetter(clickedLetter);
      }
      // Also update the URL so the letter filter is applied
      updateParam('letter', clickedLetter);
    },
    [availableLetters, updateParam]
  );

  // ── Prefix search handler ──────────────────────────────────────
  const handlePrefixSearch = useCallback((e) => {
    setPrefixQuery(e.target.value);
  }, []);

  // Clear scroll target after it's been consumed
  useEffect(() => {
    if (scrollToLetter) {
      const timeout = setTimeout(() => setScrollToLetter(null), 500);
      return () => clearTimeout(timeout);
    }
  }, [scrollToLetter]);

  // ── Build category tabs with dynamic counts ────────────────────
  // (Counts are shown inside EntityList's letter headers, but here
  //  we keep zero-count categories visible so users can still select
  //  them — they'll just see "No entities found" for that type.)
  const tabCategories = useMemo(() => {
    return CATEGORIES.map((cat) => ({
      ...cat,
      count: 0, // Total count is available from API but not needed for tabs
      visible: true,
    }));
  }, []);

  // ── Keyboard shortcut: "/" focuses the search input ────────────
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (
        e.key === '/' &&
        document.activeElement !== searchInputRef.current &&
        document.activeElement?.tagName !== 'INPUT' &&
        document.activeElement?.tagName !== 'TEXTAREA'
      ) {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div className="browse-page">
      {/* ── Top bar: type tabs + sort toggle + search ──────────── */}
      <div className="browse-top-bar">
        <CategoryTabs
          categories={tabCategories}
          selectedKey={entityType}
          onSelect={handleTypeChange}
        />

        <div className="browse-controls">
          {/* Prefix search */}
          <div className="browse-search-wrapper">
            <SearchIcon size={16} className="browse-search-icon" />
            <input
              ref={searchInputRef}
              type="text"
              className="browse-search-input"
              placeholder="Filter by prefix (e.g. Tes)…"
              value={prefixQuery}
              onChange={handlePrefixSearch}
              aria-label="Filter entities by prefix"
            />
            {prefixQuery && (
              <button
                className="browse-search-clear"
                onClick={() => setPrefixQuery('')}
                aria-label="Clear filter"
              >
                ✕
              </button>
            )}
          </div>

          {/* Sort direction toggle */}
          <button
            className="browse-sort-btn"
            onClick={handleSortToggle}
            title={`Sort ${sort === 'asc' ? 'ascending' : 'descending'}`}
            aria-label={`Sort ${sort === 'asc' ? 'ascending' : 'descending'}`}
          >
            {sort === 'asc' ? 'A→Z' : 'Z→A'}
          </button>
        </div>
      </div>

      {/* ── Main layout: letter sidebar + entity list ────────────── */}
      <div className="browse-layout" ref={scrollContainerRef}>
        <LetterIndex
          availableLetters={availableLetters}
          scrollContainerRef={scrollContainerRef}
          onLetterClick={handleLetterClick}
        />

        <div className="browse-content">
          {/* Active filters indicator */}
          {(letter || prefixQuery) && (
            <div className="browse-active-filters">
              {letter && (
                <span className="browse-filter-chip">
                  Letter: <strong>{letter}</strong>
                  <button
                    onClick={() => updateParam('letter', null)}
                    aria-label="Remove letter filter"
                  >
                    ✕
                  </button>
                </span>
              )}
              {prefixQuery && (
                <span className="browse-filter-chip">
                  Prefix: <strong>"{prefixQuery}"</strong>
                  <button
                    onClick={() => setPrefixQuery('')}
                    aria-label="Remove prefix filter"
                  >
                    ✕
                  </button>
                </span>
              )}
            </div>
          )}

          <EntityList
            entityType={entityType}
            letter={letter}
            query={prefixQuery}
            sort={sort}
            onLettersLoaded={setAvailableLetters}
            scrollToLetter={scrollToLetter}
          />
        </div>
      </div>

      {/* ── Keyboard hint ──────────────────────────────────────── */}
      <div className="browse-keyboard-hint">
        Press <kbd>/</kbd> to focus the search
      </div>
    </div>
  );
};

export default BrowsePage;
