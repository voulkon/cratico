import React, { createContext, useContext, useState, useEffect } from 'react';
import { Monitor, Sun, Sunrise, MoonStar, Moon } from 'lucide-react';
import themeDefaults from '../constants/theme.json';

const ThemeContext = createContext();

// Single source of truth for theme/palette ids and defaults. The pre-paint
// script in public/index.html mirrors these values; npm run lint:theme (also
// run on prebuild) fails if the two ever diverge.
const {
  themeIds: THEME_IDS,
  concreteThemeIds: CONCRETE_THEME_IDS,
  defaultTheme: DEFAULT_THEME,
  defaultSystemBase: DEFAULT_SYSTEM_BASE,
  palettes: PALETTES,
  defaultPalette: DEFAULT_PALETTE,
  darkCounterpart: DARK_COUNTERPART,
  lightCounterpart: LIGHT_COUNTERPART
} = themeDefaults;

const PALETTE_IDS = PALETTES.map((entry) => entry.id);

// Older builds stored "auto" for System mode. Normalize it (and discard any
// other unknown value) so a stale localStorage entry can never leave
// data-theme pointing at a block that does not exist.
const readStoredTheme = () => {
  const stored = localStorage.getItem('theme');
  const normalized = stored === 'auto' ? 'system' : stored;
  if (THEME_IDS.includes(normalized)) {
    if (stored !== normalized) localStorage.setItem('theme', normalized);
    return normalized;
  }
  if (stored) localStorage.removeItem('theme');
  return DEFAULT_THEME;
};

const readStoredSystemBase = () => {
  const stored = localStorage.getItem('system-theme-base');
  if (CONCRETE_THEME_IDS.includes(stored)) return stored;
  if (stored) localStorage.removeItem('system-theme-base');
  return DEFAULT_SYSTEM_BASE;
};

const readStoredPalette = () => {
  const stored = localStorage.getItem('palette');
  if (PALETTE_IDS.includes(stored)) return stored;
  if (stored) localStorage.removeItem('palette');
  return DEFAULT_PALETTE;
};

const prefersDarkQuery =
  typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null;

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};

export const ThemeProvider = ({ children }) => {
  const [theme, setTheme] = useState(readStoredTheme);

  const [palette, setPalette] = useState(readStoredPalette);

  // The concrete theme the "system" mode pivots around: the theme that was
  // active when the user last selected "system". Its family (plain vs
  // solarized) is preserved while following the OS preference.
  const [systemBase, setSystemBase] = useState(readStoredSystemBase);

  // Track the OS-level color scheme so the "system" theme can follow it live.
  const [systemPrefersDark, setSystemPrefersDark] = useState(
    () => (prefersDarkQuery ? prefersDarkQuery.matches : false)
  );

  useEffect(() => {
    if (!prefersDarkQuery) return undefined;
    const onChange = (event) => setSystemPrefersDark(event.matches);
    prefersDarkQuery.addEventListener('change', onChange);
    return () => prefersDarkQuery.removeEventListener('change', onChange);
  }, []);

  const themes = [
    { id: 'system', name: 'System', icon: Monitor },
    { id: 'light', name: 'Light', icon: Sun },
    { id: 'solarized-light', name: 'Solarized Light', icon: Sunrise },
    { id: 'solarized-dark', name: 'Solarized Dark', icon: MoonStar },
    { id: 'dark', name: 'Dark', icon: Moon }
  ];

  const changeTheme = (newTheme) => {
    // Entering "system": snapshot the current concrete theme as the pivot so
    // the solarized (or plain) family the user was on is kept afterwards.
    if (newTheme === 'system' && theme !== 'system') {
      setSystemBase(resolvedTheme);
      localStorage.setItem('system-theme-base', resolvedTheme);
    }
    setTheme(newTheme);
    localStorage.setItem('theme', newTheme);
  };

  const changePalette = (newPalette) => {
    setPalette(newPalette);
    localStorage.setItem('palette', newPalette);
  };

  // "system" resolves within the captured family: light-family pivots map to
  // their dark counterpart (and vice versa) based on the OS preference.
  const resolvedTheme =
    theme !== 'system'
      ? theme
      : systemPrefersDark
        ? (DARK_COUNTERPART[systemBase] || systemBase)
        : (LIGHT_COUNTERPART[systemBase] || systemBase);

  const isDark = resolvedTheme === 'dark' || resolvedTheme === 'solarized-dark';

  const toggleTheme = () => {
    // Cycle light → dark → system so the round toggle can reach all modes.
    if (theme === 'light') changeTheme('dark');
    else if (theme === 'dark') changeTheme('system');
    else changeTheme('light');
  };

  const getCurrentPaletteColor = () => {
    const currentPalette = PALETTES.find(p => p.id === palette);
    return isDark ? currentPalette?.darkColor : currentPalette?.color;
  };

  useEffect(() => {
    const root = document.documentElement;

    // Apply the RESOLVED theme (never "system") and palette to <html> so
    // :root-level custom property aliases (e.g. --bg-secondary:
    // var(--surface-secondary)) resolve against themed values, not the
    // fallback block, and the [data-theme] CSS blocks match.
    root.setAttribute('data-theme', resolvedTheme);
    root.setAttribute('data-palette', palette);

    // Optional: Add classes for additional styling
    root.className = `theme-${resolvedTheme} palette-${palette}`;

  }, [resolvedTheme, palette]);

  const value = {
    theme,
    resolvedTheme,
    systemBase,
    palette,
    themes,
    palettes: PALETTES,
    changeTheme,
    changePalette,
    toggleTheme,
    getCurrentPaletteColor,
    isDark,
    isDarkMode: isDark,
    currentThemeName: themes.find(t => t.id === theme)?.name || 'Light',
    currentPaletteName:
      PALETTES.find(p => p.id === palette)?.name ||
      PALETTES.find(p => p.id === DEFAULT_PALETTE)?.name ||
      DEFAULT_PALETTE
  };

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
};
