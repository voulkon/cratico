import React from 'react';
import { Sun, Moon, Monitor } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext';

const THEME_ICONS = {
  light: Sun,
  dark: Moon,
  system: Monitor
};

const ThemeToggle = () => {
  const { theme, toggleTheme } = useTheme();
  const Icon = THEME_ICONS[theme] || Sun;

  return (
    <button
      onClick={toggleTheme}
      style={{
        background: 'none',
        border: '2px solid var(--border-color)',
        borderRadius: '50%',
        width: '40px',
        height: '40px',
        cursor: 'pointer',
        fontSize: '16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transition: 'all 0.3s ease',
        color: 'var(--text-color)'
      }}
      aria-label={`Theme: ${theme}. Click to change`}
      title={`Theme: ${theme}. Click to cycle light → dark → system`}
    >
      <Icon size={16} />
    </button>
  );
};

export default ThemeToggle;
