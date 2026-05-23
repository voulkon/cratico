import React, { useState } from 'react';
import { useTranslation } from '../contexts/TranslationContext';
import './LanguageSwitcher.css';

const LanguageSwitcher = ({ variant = 'dropdown' }) => {
  const { language, switchLanguage, availableLanguages, getCurrentLanguage } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);

  const currentLang = getCurrentLanguage();

  if (variant === 'toggle' && availableLanguages.length === 2) {
    // Simple toggle for just two languages
    const otherLang = availableLanguages.find(lang => lang.code !== language);

    return (
      <button
        className="language-toggle"
        onClick={() => switchLanguage(otherLang.code)}
        title={`Switch to ${otherLang.nativeName}`}
      >
        <span className="language-flag">
          {otherLang.code === 'el' ? '🇬🇷' : '🇺🇸'}
        </span>
        <span className="language-code">{otherLang.code.toUpperCase()}</span>
      </button>
    );
  }

  // Dropdown variant
  return (
    <div className="language-switcher">
      <button
        className="language-button"
        onClick={() => setIsOpen(!isOpen)}
        onBlur={() => setTimeout(() => setIsOpen(false), 150)}
      >
        <span className="language-flag">
          {language === 'el' ? '🇬🇷' : '🇺🇸'}
        </span>
        <span className="language-name">{currentLang.nativeName}</span>
        <span className={`dropdown-arrow ${isOpen ? 'open' : ''}`}>▼</span>
      </button>

      {isOpen && (
        <div className="language-dropdown">
          {availableLanguages.map((lang) => (
            <button
              key={lang.code}
              className={`language-option ${lang.code === language ? 'active' : ''}`}
              onClick={() => {
                switchLanguage(lang.code);
                setIsOpen(false);
              }}
            >
              <span className="language-flag">
                {lang.code === 'el' ? '🇬🇷' : '🇺🇸'}
              </span>
              <span className="language-name">{lang.nativeName}</span>
              {lang.code === language && <span className="check-mark">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default LanguageSwitcher;
