import React, { useRef, useCallback } from 'react';
import { useTranslation } from '../contexts/TranslationContext';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { Moon, Sun, LogOut, LogIn } from 'lucide-react';
import './UserMenu.css';

// Check if Clerk is available
const isClerkAvailable = () => {
  return !!process.env.REACT_APP_CLERK_PUBLISHABLE_KEY;
};

// Lazy load Clerk components only if available
let SignInButton, SignOutButton;
if (isClerkAvailable()) {
  const clerkReact = require('@clerk/clerk-react');
  SignInButton = clerkReact.SignInButton;
  SignOutButton = clerkReact.SignOutButton;
}

const UserMenuDropdown = ({ onClose, onShowLogin }) => {
  const { t, language, switchLanguage, availableLanguages } = useTranslation();
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
  const { user, isSignedIn, isClerkAuth, signOut } = useAuth();

  const handleLanguageChange = (langCode) => {
    switchLanguage(langCode);
  };

  const handlePaletteChange = (paletteId) => {
    changePalette(paletteId);
  };

  const themeTrackRef = useRef(null);

  const themeIndex = themes.findIndex(t => t.id === theme);

  const handleThemeTrackClick = useCallback((e) => {
    if (!themeTrackRef.current) return;
    const rect = themeTrackRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const ratio = x / rect.width;
    const index = Math.round(ratio * (themes.length - 1));
    const clampedIndex = Math.max(0, Math.min(themes.length - 1, index));
    changeTheme(themes[clampedIndex].id);
  }, [themes, changeTheme]);

  const handleThemeThumbDrag = useCallback((e) => {
    e.preventDefault();
    if (!themeTrackRef.current) return;

    const onMove = (moveEvent) => {
      const rect = themeTrackRef.current.getBoundingClientRect();
      const clientX = moveEvent.touches ? moveEvent.touches[0].clientX : moveEvent.clientX;
      const x = clientX - rect.left;
      const ratio = x / rect.width;
      const index = Math.round(ratio * (themes.length - 1));
      const clampedIndex = Math.max(0, Math.min(themes.length - 1, index));
      changeTheme(themes[clampedIndex].id);
    };

    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend', onUp);
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    document.addEventListener('touchmove', onMove);
    document.addEventListener('touchend', onUp);
  }, [themes, changeTheme]);

  return (
    <div className="user-menu-dropdown">
      {/* User Section */}
      <div className="menu-section">
        {isSignedIn ? (
          <div className="user-info-centered">
            <div className="user-email-bold">{user?.primaryEmailAddress?.emailAddress || user?.email || ''}</div>
            {isClerkAuth ? (
              <SignOutButton>
                <button className="sign-out-inline" onClick={onClose} title={t('common.signOut')}>
                  <LogOut size={14} />
                </button>
              </SignOutButton>
            ) : (
              <button
                className="sign-out-inline"
                onClick={() => { onClose(); signOut(); }}
                title={t('common.signOut')}
              >
                <LogOut size={14} />
              </button>
            )}
          </div>
        ) : (
          <div className="sign-in-prompt">
            <div className="sign-in-text">Not signed in</div>
          </div>
        )}
      </div>

      <div className="menu-divider"></div>

      {/* Theme Mode Section - Draggable slider with sun/moon */}
      <div className="menu-section">
        <div
          className="theme-slider-track"
          ref={themeTrackRef}
          onClick={handleThemeTrackClick}
        >
          <Sun size={14} className="theme-slider-icon-left" />
          <div className="theme-slider-rail">
            <div
              className="theme-slider-thumb"
              style={{ left: `${(themeIndex / (themes.length - 1)) * 100}%` }}
              onMouseDown={handleThemeThumbDrag}
              onTouchStart={handleThemeThumbDrag}
            />
          </div>
          <Moon size={14} className="theme-slider-icon-right" />
        </div>
      </div>

      <div className="menu-divider"></div>

      {/* Color Palette Section */}
      <div className="menu-section">
        <div className="palette-grid">
          {palettes.map((paletteOption) => (
            <button
              key={paletteOption.id}
              className={`palette-option ${paletteOption.id === palette ? 'active' : ''}`}
              onClick={() => handlePaletteChange(paletteOption.id)}
              title={paletteOption.name}
              style={{
                backgroundColor: (theme === 'dark' || theme === 'solarized-dark') ? paletteOption.darkColor : paletteOption.color
              }}
            >
              {paletteOption.id === palette && <span className="palette-check">✓</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="menu-divider"></div>

      {/* Language Section - Full width horizontal flags */}
      <div className="menu-section">
        <div className="language-options-row">
          {availableLanguages.map((lang) => (
            <button
              key={lang.code}
              className={`language-option ${lang.code === language ? 'active' : ''}`}
              onClick={() => handleLanguageChange(lang.code)}
              title={lang.nativeName}
            >
              <span className="option-flag-large">
                {lang.code === 'el' ? '🇬🇷' : '🇺🇸'}
              </span>
              <span className="language-option-name">{lang.nativeName}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Sign In Section (only when not signed in) */}
      {!isSignedIn && (
        <div className="menu-section">
          {isClerkAuth ? (
            <SignInButton mode="modal">
              <button className="menu-action primary" onClick={onClose}>
                <LogIn size={16} /> {t('common.signIn')}
              </button>
            </SignInButton>
          ) : (
            <button
              className="menu-action primary"
              onClick={() => {
                onClose();
                onShowLogin && onShowLogin();
              }}
            >
              <LogIn size={16} /> {t('common.signIn')}
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default UserMenuDropdown;
