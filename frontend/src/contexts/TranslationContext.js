import React, { createContext, useContext, useState, useEffect } from 'react';
import en from '../locales/en.json';
import el from '../locales/el.json';

const translations = {
  en,
  el
};

const TranslationContext = createContext();

export const useTranslation = () => {
  const context = useContext(TranslationContext);
  if (!context) {
    throw new Error('useTranslation must be used within TranslationProvider');
  }
  return context;
};

export const TranslationProvider = ({ children }) => {
  // Get saved language from localStorage or default to English
  const [language, setLanguage] = useState(() => {
    const saved = localStorage.getItem('preferred-language');
    return saved || 'en';
  });

  // Save language preference
  useEffect(() => {
    localStorage.setItem('preferred-language', language);
    // Also update document language for accessibility
    document.documentElement.lang = language;
  }, [language]);

  // Translation function with nested key support and interpolation
  const t = (key, params = {}) => {
    const keys = key.split('.');
    let value = translations[language];

    // Navigate through nested keys
    for (const k of keys) {
      value = value?.[k];
      if (value === undefined) {
        console.warn(`Translation missing for key: ${key} in language: ${language}`);
        // Fallback to English if key doesn't exist
        value = translations.en;
        for (const k of keys) {
          value = value?.[k];
          if (value === undefined) {
            return key; // Return the key if not found in any language
          }
        }
        break;
      }
    }

    if (typeof value !== 'string') {
      console.warn(`Translation value is not a string for key: ${key}`);
      return key;
    }

    // Replace interpolation parameters {param} with actual values
    return value.replace(/\{(\w+)\}/g, (match, param) => {
      return params[param] !== undefined ? params[param] : match;
    });
  };

  const switchLanguage = (newLanguage) => {
    if (translations[newLanguage]) {
      setLanguage(newLanguage);
    } else {
      console.warn(`Language ${newLanguage} not supported`);
    }
  };

  const availableLanguages = [
    { code: 'en', name: 'English', nativeName: 'English' },
    { code: 'el', name: 'Greek', nativeName: 'Ελληνικά' }
  ];

  const getCurrentLanguage = () => {
    return availableLanguages.find(lang => lang.code === language) || availableLanguages[0];
  };

  const value = {
    language,
    t,
    switchLanguage,
    availableLanguages,
    getCurrentLanguage,
    isRTL: language === 'ar' || language === 'he', // Add RTL support if needed
  };

  return (
    <TranslationContext.Provider value={value}>
      {children}
    </TranslationContext.Provider>
  );
};
