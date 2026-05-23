import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { BookOpenIcon } from './Icons';
import { Moon, Sun, Palette, LogOut, LogIn } from 'lucide-react';
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
  const navigate = useNavigate();
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

  const handleThemeChange = (themeId) => {
    changeTheme(themeId);
  };

  const handlePaletteChange = (paletteId) => {
    changePalette(paletteId);
  };

  return (
    <div className="user-menu-dropdown">
      {/* User Section */}
      <div className="menu-section">
        {isSignedIn ? (
          <div className="user-info">
            <div className="user-details">
              <div className="user-name">{user?.firstName} {user?.lastName}</div>
              <div className="user-email">{user?.primaryEmailAddress?.emailAddress}</div>
            </div>
          </div>
        ) : (
          <div className="sign-in-prompt">
            <div className="sign-in-text">Not signed in</div>
          </div>
        )}
      </div>

      <div className="menu-divider"></div>

      {/* Library Link */}
      <div className="menu-section">
        <button
          className="menu-action primary"
          onClick={() => {
            onClose();
            navigate('/library');
          }}
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}
        >
          <BookOpenIcon size={16} />
          <span>{t('library.myLibrary')}</span>
        </button>
      </div>

      <div className="menu-divider"></div>

      {/* Language Section - Compact horizontal flags */}
      <div className="menu-section">
        <div className="menu-section-label">{t('common.language')}</div>
        <div className="compact-options-row">
          {availableLanguages.map((lang) => (
            <button
              key={lang.code}
              className={`compact-option ${lang.code === language ? 'active' : ''}`}
              onClick={() => handleLanguageChange(lang.code)}
              title={lang.nativeName}
            >
              <span className="option-flag-large">
                {lang.code === 'el' ? '🇬🇷' : '🇺🇸'}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="menu-divider"></div>

      {/* Theme Mode Section - Compact horizontal icons */}
      <div className="menu-section">
        <div className="menu-section-label">
          <span className="section-icon">{theme === 'dark' ? <Moon size={16} /> : <Sun size={16} />}</span>
          {t('common.themeMode')}
        </div>
        <div className="compact-options-row">
          {themes.map((themeOption) => (
            <button
              key={themeOption.id}
              className={`compact-option ${themeOption.id === theme ? 'active' : ''}`}
              onClick={() => handleThemeChange(themeOption.id)}
              title={themeOption.name}
            >
              <span className="option-icon-large">{themeOption.icon}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="menu-divider"></div>

      {/* Color Palette Section - No names */}
      <div className="menu-section">
        <div className="menu-section-label">
          <span className="section-icon"><Palette size={16} /></span>
          {t('common.colorPalette')}
        </div>
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

      {/* Show current theme info */}
      <div className="menu-divider"></div>
      <div className="menu-section">
        <div className="current-theme-display">
          <span className="current-theme-label">Current:</span>
          <span className="current-theme-value">
            {currentThemeName} • {currentPaletteName}
          </span>
        </div>
      </div>

      <div className="menu-divider"></div>

      {/* Authentication Section */}
      <div className="menu-section">
        {isSignedIn && isClerkAuth ? (
          <SignOutButton>
            <button className="menu-action danger" onClick={onClose}>
              <LogOut size={16} /> {t('common.signOut')}
            </button>
          </SignOutButton>
        ) : isSignedIn && !isClerkAuth ? (
          <button
            className="menu-action danger"
            onClick={() => {
              onClose();
              signOut();
            }}
          >
            <LogOut size={16} /> {t('common.signOut')}
          </button>
        ) : isClerkAuth ? (
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
    </div>
  );
};

export default UserMenuDropdown;
