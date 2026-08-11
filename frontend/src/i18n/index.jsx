import React, { createContext, useContext, useState, useCallback } from 'react';
import en from './locales/en';
import vi from './locales/vi';
import ja from './locales/ja';
import ko from './locales/ko';
import zh from './locales/zh';

const LOCALES = { en, vi, ja, ko, zh };
const STORAGE_KEY = 'srvdash_lang';

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(
    () => localStorage.getItem(STORAGE_KEY) || 'en'
  );

  const setLang = useCallback((newLang) => {
    localStorage.setItem(STORAGE_KEY, newLang);
    setLangState(newLang);
  }, []);

  const t = useCallback((key, vars) => {
    const resolve = (locale) => {
      const parts = key.split('.');
      let node = locale;
      for (const part of parts) {
        if (node == null || typeof node !== 'object') return undefined;
        node = node[part];
      }
      return typeof node === 'string' ? node : undefined;
    };

    const currentLocale = LOCALES[lang] || LOCALES.en;
    let str = resolve(currentLocale) ?? resolve(LOCALES.en) ?? key;

    if (vars) {
      str = str.replace(/\{(\w+)\}/g, (_, name) =>
        vars[name] !== undefined ? String(vars[name]) : '{' + name + '}'
      );
    }

    return str;
  }, [lang]);

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useTranslation() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useTranslation must be used inside I18nProvider');
  return ctx;
}

export const SUPPORTED_LANGS = [
  { code: 'en', label: 'EN', flag: '🇺🇸', name: 'English' },
  { code: 'vi', label: 'VI', flag: '🇻🇳', name: 'Tiếng Việt' },
  { code: 'ja', label: 'JA', flag: '🇯🇵', name: '日本語' },
  { code: 'ko', label: 'KO', flag: '🇰🇷', name: '한국어' },
  { code: 'zh', label: 'ZH', flag: '🇨🇳', name: '中文' },
];
