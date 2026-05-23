import React, { createContext, useContext, useState, useEffect } from 'react';

const ThemeContext = createContext();

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};

export const ThemeProvider = ({ children }) => {
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem('theme') || 'light';
  });

  const [palette, setPalette] = useState(() => {
    return localStorage.getItem('palette') || 'blue';
  });

  const themes = [
    { id: 'light', name: 'Light', icon: '☀️' },
    { id: 'solarized-light', name: 'Solarized Light', icon: '🌤️' },
    { id: 'solarized-dark', name: 'Solarized Dark', icon: '🌆' },
    { id: 'dark', name: 'Dark', icon: '🌙' }
  ];

  const palettes = [
    { id: 'blue', name: 'Blue', color: '#4299E1', darkColor: '#63B3ED' },
    { id: 'purple', name: 'Purple', color: '#8b5cf6', darkColor: '#a78bfa' },
    { id: 'green', name: 'Green', color: '#10b981', darkColor: '#34d399' },
    { id: 'orange', name: 'Orange', color: '#f59e0b', darkColor: '#fbbf24' },
    { id: 'red', name: 'Red', color: '#ef4444', darkColor: '#f87171' },
    { id: 'pink', name: 'Pink', color: '#ec4899', darkColor: '#f472b6' }
  ];

  const changeTheme = (newTheme) => {
    setTheme(newTheme);
    localStorage.setItem('theme', newTheme);
  };

  const changePalette = (newPalette) => {
    setPalette(newPalette);
    localStorage.setItem('palette', newPalette);
  };

  const getCurrentPaletteColor = () => {
    const currentPalette = palettes.find(p => p.id === palette);
    const isDarkTheme = theme === 'dark' || theme === 'solarized-dark';
    return isDarkTheme ? currentPalette?.darkColor : currentPalette?.color;
  };

  useEffect(() => {
    const body = document.body;

    // Apply theme and palette
    body.setAttribute('data-theme', theme);
    body.setAttribute('data-palette', palette);

    // Optional: Add classes for additional styling
    body.className = `theme-${theme} palette-${palette}`;

  }, [theme, palette]);

  const value = {
    theme,
    palette,
    themes,
    palettes,
    changeTheme,
    changePalette,
    getCurrentPaletteColor,
    isDark: theme === 'dark' || theme === 'solarized-dark',
    currentThemeName: themes.find(t => t.id === theme)?.name || 'Light',
    currentPaletteName: palettes.find(p => p.id === palette)?.name || 'Blue'
  };

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
};
