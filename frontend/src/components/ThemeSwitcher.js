import React, { useState, useRef, useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import './ThemeSwitcher.css';

const ThemeSwitcher = ({ compact = false }) => {
  const {
    theme,
    palette,
    themes,
    palettes,
    changeTheme,
    changePalette,
    currentThemeName,
    currentPaletteName
  } = useTheme();

  const [isExpanded, setIsExpanded] = useState(false);
  const dropdownRef = useRef(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsExpanded(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const getCurrentThemeIcon = () => {
    const currentTheme = themes.find(t => t.id === theme);
    return currentTheme ? currentTheme.icon : '🎨';
  };

  const getCurrentPaletteColor = () => {
    const currentPalette = palettes.find(p => p.id === palette);
    if (!currentPalette) return '#4299E1';
    const isDarkTheme = theme === 'dark' || theme === 'solarized-dark';
    return isDarkTheme ? currentPalette.darkColor : currentPalette.color;
  };

  if (compact) {
    return (
      <div className="theme-switcher-compact" ref={dropdownRef}>
        <button
          className="theme-toggle-button"
          onClick={() => setIsExpanded(!isExpanded)}
          title={`${currentThemeName} ${currentPaletteName} Theme`}
          style={{
            borderLeft: `3px solid ${getCurrentPaletteColor()}`
          }}
        >
          <span className="theme-icon">{getCurrentThemeIcon()}</span>
          <span className="theme-text">Theme</span>
          <span className={`dropdown-arrow ${isExpanded ? 'expanded' : ''}`}>
            ▼
          </span>
        </button>

        {isExpanded && (
          <div className="theme-dropdown">
            <div className="theme-section">
              <h4>
                <span className="section-icon">🌓</span>
                Mode
              </h4>
              <div className="theme-buttons">
                {themes.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => {
                      changeTheme(t.id);
                      // Don't close dropdown immediately for better UX
                    }}
                    className={`theme-button ${theme === t.id ? 'active' : ''}`}
                    title={`Switch to ${t.name} mode`}
                  >
                    <span className="theme-icon">{t.icon}</span>
                    <span className="theme-name">{t.name}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="theme-section">
              <h4>
                <span className="section-icon">🎨</span>
                Colors
              </h4>
              <div className="palette-grid">
                {palettes.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => {
                      changePalette(p.id);
                      // Auto-close after palette selection for cleaner UX
                      setTimeout(() => setIsExpanded(false), 300);
                    }}
                    className={`palette-button ${palette === p.id ? 'active' : ''}`}
                    title={`${p.name} color palette`}
                    style={{
                      backgroundColor: (theme === 'dark' || theme === 'solarized-dark') ? p.darkColor : p.color
                    }}
                  >
                    {palette === p.id && <span className="check-mark">✓</span>}
                    <span className="palette-tooltip">{p.name}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="theme-footer">
              <div className="current-selection">
                <strong>{currentThemeName}</strong> • <strong>{currentPaletteName}</strong>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="theme-switcher">
      <div className="theme-switcher-header">
        <h3 className="theme-switcher-title">🎨 Customize Appearance</h3>
        <div className="current-theme-info">
          Current: <strong>{currentThemeName} {currentPaletteName}</strong>
        </div>
      </div>

      <div className="theme-control-section">
        <div className="theme-control-group">
          <label className="theme-label">Theme Mode:</label>
          <div className="theme-buttons">
            {themes.map((t) => (
              <button
                key={t.id}
                onClick={() => changeTheme(t.id)}
                className={`theme-button ${theme === t.id ? 'active' : ''}`}
              >
                <span className="theme-icon">{t.icon}</span>
                <span className="theme-name">{t.name}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="theme-control-group">
          <label className="theme-label">Color Palette:</label>
          <div className="palette-grid">
            {palettes.map((p) => (
              <button
                key={p.id}
                onClick={() => changePalette(p.id)}
                className={`palette-button ${palette === p.id ? 'active' : ''}`}
                title={`${p.name} - ${(theme === 'dark' || theme === 'solarized-dark') ? 'Dark' : 'Light'} Mode`}
              >
                <div
                  className="palette-color-preview"
                  style={{
                    backgroundColor: (theme === 'dark' || theme === 'solarized-dark') ? p.darkColor : p.color
                  }}
                >
                  {palette === p.id && <span className="check-mark">✓</span>}
                </div>
                <span className="palette-name">{p.name}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="theme-preview">
        <div className="preview-card">
          <div className="preview-header">Theme Preview</div>
          <div className="preview-content">
            <div className="preview-button">Primary Button</div>
            <div className="preview-text">Sample text content</div>
            <div className="preview-accent">Accent color</div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ThemeSwitcher;
