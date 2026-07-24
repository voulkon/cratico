import React, { useEffect, useRef, useState } from 'react';
import CategoryTabs from './CategoryTabs';
import { ChevronLeft, ChevronRight } from './Icons';
import './ScrollableCategoryTabs.css';

/**
 * ScrollableCategoryTabs — wraps CategoryTabs with left/right scroll
 * buttons that appear only when the tab strip overflows its container.
 *
 * Solves two problems on narrow screens:
 *  1. Hidden tabs become reachable via explicit ‹ › affordances.
 *  2. The native horizontal scroll is non-obvious; the buttons make
 *     overflow discoverable.
 *
 * Passes through all CategoryTabs props unchanged.
 */
const ScrollableCategoryTabs = ({ categories, selectedKey, onSelect, className = '' }) => {
  const scrollRef = useRef(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  // One-time pulse to draw the eye to the arrows the first time the
  // tab strip overflows. Cleared after the animation runs so it never
  // repeats in the same mount (avoids nagging on every resize/scroll).
  const [pulse, setPulse] = useState(false);
  const hasPulsedRef = useRef(false);

  // Amount to scroll per click — one "page" of tabs (container width),
  // clamped so a single click always advances at least one tab.
  const scrollByPage = (dir) => {
    const el = scrollRef.current;
    if (!el) return;
    const delta = dir * Math.max(el.clientWidth * 0.8, 60);
    el.scrollBy({ left: delta, behavior: 'smooth' });
  };

  // Recompute arrow visibility on scroll, resize, and when the
  // selected tab / category list changes. Also fires a one-time
  // attention pulse the first time overflow is detected.
  const updateScrollState = () => {
    const el = scrollRef.current;
    if (!el) return;
    const overflow = el.scrollWidth - el.clientWidth;
    const left = el.scrollLeft > 2;
    const right = el.scrollLeft < overflow - 2;
    setCanScrollLeft(left);
    setCanScrollRight(right);
    // Trigger the pulse once, the first time either side overflows.
    if ((left || right) && !hasPulsedRef.current) {
      hasPulsedRef.current = true;
      setPulse(true);
      // Remove the class after the animation so it can't re-trigger.
      window.setTimeout(() => setPulse(false), 1800);
    }
  };

  useEffect(() => {
    updateScrollState();
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener('scroll', updateScrollState, { passive: true });
    window.addEventListener('resize', updateScrollState);
    return () => {
      el.removeEventListener('scroll', updateScrollState);
      window.removeEventListener('resize', updateScrollState);
    };
  }, [categories, selectedKey]);

  // Keep the active tab visible after selection changes.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const active = el.querySelector('.category-tab.active');
    if (active) {
      const aLeft = active.offsetLeft;
      const aRight = aLeft + active.offsetWidth;
      if (aLeft < el.scrollLeft) {
        el.scrollTo({ left: aLeft - 8, behavior: 'smooth' });
      } else if (aRight > el.scrollLeft + el.clientWidth) {
        el.scrollTo({ left: aRight - el.clientWidth + 8, behavior: 'smooth' });
      }
    }
    updateScrollState();
  }, [selectedKey]);

  return (
    <div className={`scrollable-category-tabs${className ? ' ' + className : ''}`}>
      <button
        type="button"
        className={`sct-arrow sct-arrow-left${pulse ? ' sct-pulse' : ''}`}
        onClick={() => scrollByPage(-1)}
        disabled={!canScrollLeft}
        aria-label="Scroll categories left"
        tabIndex={-1}
      >
        <ChevronLeft size={16} />
      </button>
      <div className="sct-scroll" ref={scrollRef}>
        <CategoryTabs
          categories={categories}
          selectedKey={selectedKey}
          onSelect={onSelect}
        />
      </div>
      <button
        type="button"
        className={`sct-arrow sct-arrow-right${pulse ? ' sct-pulse' : ''}`}
        onClick={() => scrollByPage(1)}
        disabled={!canScrollRight}
        aria-label="Scroll categories right"
        tabIndex={-1}
      >
        <ChevronRight size={16} />
      </button>
    </div>
  );
};

export default ScrollableCategoryTabs;
