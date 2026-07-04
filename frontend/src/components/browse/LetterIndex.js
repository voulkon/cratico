import React, { useCallback, useEffect, useRef, useState } from 'react';
import './LetterIndex.css';

const GREEK_LETTERS = Array.from({ length: 24 }, (_, i) =>
  String.fromCharCode(0x0391 + i)
); // Α-Ω

const LATIN_LETTERS = Array.from({ length: 26 }, (_, i) =>
  String.fromCharCode(0x41 + i)
); // A-Z

/**
 * LetterIndex — a vertical sidebar showing available first letters.
 *
 * Highlights the letter whose heading is currently closest to the top of
 * the viewport. Clicking a letter scrolls the page so that heading is at
 * the top.
 *
 * Props:
 *   availableLetters  - string[] — which letters to show (from API)
 *   scrollContainerRef - React ref to the scrollable container
 *   onLetterClick     - (letter: string) => void — optional callback
 */
const LetterIndex = ({ availableLetters = [], scrollContainerRef, onLetterClick }) => {
  const [activeLetter, setActiveLetter] = useState(null);
  const observerRef = useRef(null);
  const headingPositionsRef = useRef({});

  // Build a set for O(1) lookup
  const availableSet = new Set(availableLetters);

  // All letters to display (Greek + Latin that are available)
  const displayLetters = [...GREEK_LETTERS, ...LATIN_LETTERS].filter((l) =>
    availableSet.has(l)
  );

  // ── IntersectionObserver: detect which letter is in view ──────
  const updateActiveLetter = useCallback(() => {
    const container = scrollContainerRef?.current;
    if (!container) return;

    const containerTop = container.getBoundingClientRect().top;
    // Offset so the letter header isn't hidden behind any sticky bar
    const stickyOffset = 120;

    let closestLetter = null;
    let closestDistance = Infinity;

    Object.entries(headingPositionsRef.current).forEach(([letter, el]) => {
      const rect = el.getBoundingClientRect();
      const distance = rect.top - containerTop - stickyOffset;
      if (distance <= 0 && Math.abs(distance) < closestDistance) {
        closestDistance = Math.abs(distance);
        closestLetter = letter;
      }
    });

    // Fallback: first letter whose heading hasn't scrolled past
    if (!closestLetter) {
      for (const [letter, el] of Object.entries(headingPositionsRef.current)) {
        const rect = el.getBoundingClientRect();
        if (rect.top >= containerTop) {
          closestLetter = letter;
          break;
        }
      }
    }

    if (closestLetter && closestLetter !== activeLetter) {
      setActiveLetter(closestLetter);
    }
  }, [scrollContainerRef, activeLetter]);

  useEffect(() => {
    const container = scrollContainerRef?.current;
    if (!container) return;

    container.addEventListener('scroll', updateActiveLetter, { passive: true });
    return () => container.removeEventListener('scroll', updateActiveLetter);
  }, [scrollContainerRef, updateActiveLetter]);

  // ── Register heading elements ──────────────────────────────────
  useEffect(() => {
    // Re-scan for letter heading markers in the DOM
    const scan = () => {
      const headings = {};
      document.querySelectorAll('[data-letter-heading]').forEach((el) => {
        headings[el.dataset.letterHeading] = el;
      });
      headingPositionsRef.current = headings;
    };

    scan();
    // Re-scan whenever results change (the EntityList will render new headings)
    const id = setInterval(scan, 500);
    return () => clearInterval(id);
  }, [availableLetters]); // re-scan when available letters change

  // Initial scan + update
  useEffect(() => {
    const timeout = setTimeout(updateActiveLetter, 100);
    return () => clearTimeout(timeout);
  }, [updateActiveLetter]);

  // ── Click handler ──────────────────────────────────────────────
  const handleLetterClick = (letter) => {
    setActiveLetter(letter);

    // Dispatch custom event so EntityList can scroll to the heading
    if (onLetterClick) {
      onLetterClick(letter);
      return;
    }

    // Default: find and scroll to the heading in DOM
    const el = document.querySelector(`[data-letter-heading="${letter}"]`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  if (displayLetters.length === 0) {
    return (
      <div className="letter-index letter-index--empty">
        <span className="letter-index-empty-text">—</span>
      </div>
    );
  }

  return (
    <nav className="letter-index" aria-label="Alphabetical index">
      <ul className="letter-index-list">
        {displayLetters.map((letter) => (
          <li key={letter}>
            <button
              className={`letter-index-btn ${activeLetter === letter ? 'active' : ''}`}
              onClick={() => handleLetterClick(letter)}
              title={`Jump to ${letter}`}
              aria-current={activeLetter === letter ? 'true' : undefined}
            >
              {letter}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
};

export default LetterIndex;
