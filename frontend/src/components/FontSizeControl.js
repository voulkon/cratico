import React, { useEffect, useState } from 'react';
import './FontSizeControl.css';

const STORAGE_KEY = 'app-font-scale';
const MIN = 0.3;
const MAX = 1.7;
const STEP = 0.1;
const DEFAULT = 1.0;

const clamp = (v) => Math.min(MAX, Math.max(MIN, parseFloat(v.toFixed(2))));

/**
 * FontSizeControl — −/+ split button that scales all text via --font-scale.
 * Uses SplitButton CSS classes for identical sizing/appearance to other controls.
 * Persists to localStorage; applied to :root on mount and on every change.
 */
const FontSizeControl = () => {
  const [scale, setScale] = useState(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? clamp(parseFloat(saved)) : DEFAULT;
  });

  useEffect(() => {
    document.documentElement.style.setProperty('--font-scale', scale);
    localStorage.setItem(STORAGE_KEY, scale);
  }, [scale]);

  const decrease = () => setScale((s) => clamp(s - STEP));
  const increase = () => setScale((s) => clamp(s + STEP));

  return (
    <div
      className="split-button font-size-control"
      title={`Font size: ${Math.round(scale * 100)}%`}
    >
      <button
        className="split-button-main font-size-btn"
        onClick={decrease}
        disabled={scale <= MIN}
        title={`Decrease font size (${Math.round(scale * 100)}%)`}
        aria-label="Decrease font size"
      >
        −
      </button>
      <button
        className="split-button-chevron font-size-btn font-size-btn--increase"
        onClick={increase}
        disabled={scale >= MAX}
        title={`Increase font size (${Math.round(scale * 100)}%)`}
        aria-label="Increase font size"
      >
        +
      </button>
    </div>
  );
};

export default FontSizeControl;

