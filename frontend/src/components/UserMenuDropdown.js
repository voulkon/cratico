import React, { useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { Moon, Sun, LogOut, LogIn, Sparkles, Check, Monitor, Bell } from 'lucide-react';
// Static import is safe: <SignOutButton> is only RENDERED when a Clerk
// session exists (isClerkAuth), which implies ClerkProvider is mounted in
// index.js. Sign-in goes through the unified DjangoLoginForm modal instead,
// so SignInButton is no longer needed here.
import { SignOutButton } from '@clerk/clerk-react';
import RateLimitIndicator from './RateLimitIndicator';
import './UserMenu.css';

const UserMenuDropdown = ({ onClose, onShowLogin }) => {
  const navigate = useNavigate();
  const { t, language, switchLanguage, availableLanguages } = useTranslation();
  const {
    theme,
    resolvedTheme,
    palette,
    themes,
    palettes,
    changeTheme,
    changePalette,
    isDark
  } = useTheme();
  const { user, isSignedIn, isClerkAuth, signOut } = useAuth();

  // The slider is a lightness spectrum (light → solarized-light →
  // solarized-dark → dark). "System" is not on that spectrum, so it gets its
  // own toggle; while system mode is active the thumb rests at the RESOLVED
  // theme's position and the rail is dimmed. Interacting with the slider
  // implicitly exits system mode (changeTheme with a concrete id).
  const spectrumThemes = themes.filter(t => t.id !== 'system');

  const handleLanguageChange = (langCode) => {
    switchLanguage(langCode);
  };

  const handlePaletteChange = (paletteId) => {
    changePalette(paletteId);
  };

  const themeTrackRef = useRef(null);

  const themeIndex = spectrumThemes.findIndex(t => t.id === resolvedTheme);

  const handleThemeTrackClick = useCallback((e) => {
    if (!themeTrackRef.current) return;
    const rect = themeTrackRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const ratio = x / rect.width;
    const index = Math.round(ratio * (spectrumThemes.length - 1));
    const clampedIndex = Math.max(0, Math.min(spectrumThemes.length - 1, index));
    changeTheme(spectrumThemes[clampedIndex].id);
  }, [spectrumThemes, changeTheme]);

  const handleThemeThumbDrag = useCallback((e) => {
    e.preventDefault();
    if (!themeTrackRef.current) return;

    const onMove = (moveEvent) => {
      const rect = themeTrackRef.current.getBoundingClientRect();
      const clientX = moveEvent.touches ? moveEvent.touches[0].clientX : moveEvent.clientX;
      const x = clientX - rect.left;
      const ratio = x / rect.width;
      const index = Math.round(ratio * (spectrumThemes.length - 1));
      const clampedIndex = Math.max(0, Math.min(spectrumThemes.length - 1, index));
      changeTheme(spectrumThemes[clampedIndex].id);
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
  }, [spectrumThemes, changeTheme]);

  return (
    <div className="user-menu-dropdown">
      {/* User Section */}
      <div className="menu-section">
        {isSignedIn ? (
          <div className="user-info-centered">
            <div className="user-email-bold">{user?.primaryEmailAddress?.emailAddress || user?.email || ''}</div>
            {isClerkAuth ? (
              // SignOutButton only ends the Clerk session; the combined
              // signOut() also clears any residual Django token, so it runs
              // alongside (not instead of) Clerk's own sign-out.
              <SignOutButton>
                <button
                  className="sign-out-inline"
                  onClick={() => { onClose(); signOut(); }}
                  title={t('common.signOut')}
                >
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
            <div className="sign-in-text">{t('common.notSignedIn')}</div>
          </div>
        )}
      </div>

      <div className="menu-divider"></div>

      {/* Theme Mode Section - draggable lightness slider + System toggle */}
      <div className="menu-section">
        <div
          className={`theme-slider-track ${theme === 'system' ? 'auto' : ''}`}
          ref={themeTrackRef}
          onClick={handleThemeTrackClick}
        >
          <Sun size={14} className="theme-slider-icon-left" />
          <div className="theme-slider-rail">
            {spectrumThemes.map((t, i) => (
              <div
                key={t.id}
                className={`theme-slider-stop ${i === themeIndex ? 'active' : ''}`}
                style={{ left: `${(i / (spectrumThemes.length - 1)) * 100}%` }}
                title={t.name}
              />
            ))}
            <div
              className="theme-slider-thumb"
              style={{ left: `${(themeIndex / (spectrumThemes.length - 1)) * 100}%` }}
              onMouseDown={handleThemeThumbDrag}
              onTouchStart={handleThemeThumbDrag}
            />
          </div>
          <Moon size={14} className="theme-slider-icon-right" />
        </div>
        <button
          type="button"
          className={`theme-system-toggle ${theme === 'system' ? 'active' : ''}`}
          onClick={() => changeTheme(theme === 'system' ? resolvedTheme : 'system')}
          title={t('common.systemTheme')}
        >
          <Monitor size={14} />
          <span>{t('common.systemTheme')}</span>
        </button>
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
                backgroundColor: isDark ? paletteOption.darkColor : paletteOption.color
              }}
            >
              {paletteOption.id === palette && <span className="palette-check"><Check size={10} /></span>}
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

      {/* Sign In Section (only when not signed in). One button: the Django
          login modal itself offers every active method (Clerk + email), so no
          stacked method buttons are needed here. */}
      {!isSignedIn && (
        <div className="menu-section">
          <button
            className="menu-action primary"
            onClick={() => {
              onClose();
              onShowLogin && onShowLogin();
            }}
          >
            <LogIn size={16} /> {t('common.signIn')}
          </button>
        </div>
      )}

      {/* AI (only when signed in) */}
      {isSignedIn && (
        <>
          <div className="menu-divider"></div>
          <div className="menu-section">
            <button
              className="menu-action"
              style={{ justifyContent: 'center', textAlign: 'center' }}
              onClick={() => {
                onClose();
                navigate('/settings/notifications');
              }}
            >
              <Bell size={16} /> {t('notificationSettings.title')}
            </button>
            <button
              className="menu-action"
              style={{ justifyContent: 'center', textAlign: 'center' }}
              onClick={() => {
                onClose();
                navigate('/ai/settings');
              }}
            >
              <Sparkles size={16} /> {t('common.ai')}
            </button>
          </div>
        </>
      )}

      {/* Daily API quota, fed by X-RateLimit-* headers via api/client.js.
          Kept at the bottom as informational footer; renders its own divider
          and section, and nothing at all until a rate-limit response has
          actually been seen. */}
      <RateLimitIndicator label={t('common.requestsRemaining')} />
    </div>
  );
};

export default UserMenuDropdown;
