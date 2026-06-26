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
 * Props:
 *   entityType  - 'all' | 'organization' | 'signer' | 'unit' |
 *                 'company' | 'companyperson' | 'afmentity'
 *   letter      - first-letter filter (optional)
 *   query       - free-text prefix filter (optional)
 *   sort        - 'asc' | 'desc'
 *   onLettersLoaded - callback(letters[]) — inform parent of available letters
 *   scrollToLetter  - string | null — when set, scroll to this letter's heading
 */
const EntityList = ({
  entityType = 'all',
  letter = null,
  query = null,
  sort = 'asc',
  onLettersLoaded,
  scrollToLetter,
}) => {
  const navigate = useNavigate();

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState(null);

  const offsetRef = useRef(0);
  const isFirstLoad = useRef(true);
  const queryRef = useRef(null);

  // ── Reset when filters change ──────────────────────────────────
  useEffect(() => {
    setItems([]);
    setHasMore(true);
    setError(null);
    offsetRef.current = 0;
    isFirstLoad.current = true;
  }, [entityType, letter, query, sort]);

  // ── Fetch a page ───────────────────────────────────────────────
  const fetchPage = useCallback(
    async (loadMore = false) => {
      // Prevent duplicate inflight requests
      if (queryRef.current) return;
      queryRef.current = true;

      if (!loadMore) {
        setLoading(true);
      } else {
        setLoadingMore(true);
      }
      setError(null);

      try {
        const params = {
          type: entityType,
          sort,
          offset: loadMore ? offsetRef.current : 0,
          limit: 50,
        };
        if (letter) params.letter = letter;
        if (query && query.trim()) params.q = query.trim();

        const data = await fetchBrowseEntities(params);

        if (loadMore) {
          setItems((prev) => [...prev, ...data.results]);
        } else {
          setItems(data.results);
        }

        setHasMore(data.has_more);
        offsetRef.current += data.results.length;

        // Notify parent of available letters on first load
        if (!loadMore && onLettersLoaded && data.available_letters) {
          onLettersLoaded(data.available_letters);
        }
      } catch (err) {
        console.error('Browse fetch failed:', err);
        setError(err.message || 'Failed to load entities');
      } finally {
        setLoading(false);
        setLoadingMore(false);
        queryRef.current = null;
      }
    },
    [entityType, letter, query, sort, onLettersLoaded]
  );

  // Initial load
  useEffect(() => {
    fetchPage(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityType, letter, query, sort]);

  // ── Infinite scroll ────────────────────────────────────────────
  const handleLoadMore = useCallback(() => {
    if (!hasMore || loading || loadingMore) return;
    fetchPage(true);
  }, [hasMore, loading, loadingMore, fetchPage]);

  const { sentinelRef } = useInfiniteScroll({
    hasMore,
    loading,
    loadingMore,
    onLoadMore: handleLoadMore,
    enabled: items.length > 0,
  });

  // ── Group by first letter ──────────────────────────────────────
  const groups = useMemo(() => {
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
  }, [items]);

  // ── Scroll to letter ───────────────────────────────────────────
  useEffect(() => {
    if (!scrollToLetter || items.length === 0) return;

    // Find the heading for this letter
    const el = document.querySelector(
      `[data-letter-heading="${scrollToLetter}"]`
    );
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [scrollToLetter, items]);

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
  if (loading && !loadingMore) {
    return <div className="entity-list">{renderSkeleton()}</div>;
  }

  if (error && items.length === 0) {
    return (
      <div className="entity-list entity-list--error">
        <div className="entity-list-error">
          <p>{error}</p>
          <button
            className="entity-list-retry-btn"
            onClick={() => fetchPage(false)}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!loading && items.length === 0) {
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
              <span className="entity-list-row-type">{item.type}</span>
            </div>
          ))}
        </div>
      ))}

      {/* Infinite scroll sentinel */}
      <div ref={sentinelRef} className="entity-list-sentinel" />

      {loadingMore && (
        <div className="entity-list-loading-more">
          <div className="entity-list-spinner" />
          <span>Loading more…</span>
        </div>
      )}

      {!hasMore && items.length > 0 && (
        <div className="entity-list-end">— End of results —</div>
      )}
    </div>
  );
};

export default EntityList;
