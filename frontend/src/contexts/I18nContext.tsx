import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import { en } from "../locales/en";
import { zh } from "../locales/zh";
import { zh_TW } from "../locales/zh-TW";
import { ja } from "../locales/ja";
import { ko } from "../locales/ko";
import { hi } from "../locales/hi";
import { vi } from "../locales/vi";
import { th } from "../locales/th";

export const LANGS = [
  { code: "en", label: "English", flag: "🇺🇸" },
  { code: "zh", label: "简体中文", flag: "🇨🇳" },
  { code: "zh-TW", label: "繁體中文", flag: "🇹🇼" },
  { code: "ja", label: "日本語", flag: "🇯🇵" },
  { code: "ko", label: "한국어", flag: "🇰🇷" },
  { code: "hi", label: "हिन्दी", flag: "🇮🇳" },
  { code: "vi", label: "Tiếng Việt", flag: "🇻🇳" },
  { code: "th", label: "ไทย", flag: "🇹🇭" },
] as const;

export type Lang = (typeof LANGS)[number]["code"];

const translations: Record<Lang, Record<string, string>> = {
  en,
  zh,
  "zh-TW": zh_TW,
  ja,
  ko,
  hi,
  vi,
  th,
};

const STORAGE_KEY = "octofinance-lang";
const LANG_CODES = LANGS.map((l) => l.code) as readonly string[];

type TranslationKey = keyof typeof en;

interface I18nContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  /** Cycles to the next language. Kept for keyboard/legacy callers. */
  toggleLang: () => void;
  t: (key: TranslationKey) => string;
}

const I18nContext = createContext<I18nContextValue>({
  lang: "en",
  setLang: () => {},
  toggleLang: () => {},
  t: (key) => key,
});

/** Pick a sensible default from the browser's language list. */
function detectLang(): Lang {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved && LANG_CODES.includes(saved)) return saved as Lang;

  for (const raw of navigator.languages ?? [navigator.language]) {
    if (!raw) continue;
    const tag = raw.toLowerCase();
    // Chinese needs script/region disambiguation before the generic prefix match
    if (tag.startsWith("zh")) {
      return /hant|tw|hk|mo/.test(tag) ? "zh-TW" : "zh";
    }
    const match = LANG_CODES.find((c) => tag === c.toLowerCase() || tag.startsWith(`${c.toLowerCase()}-`));
    if (match) return match as Lang;
  }
  return "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang);

  const setLang = useCallback((next: Lang) => {
    localStorage.setItem(STORAGE_KEY, next);
    document.documentElement.lang = next;
    setLangState(next);
  }, []);

  const toggleLang = useCallback(() => {
    setLangState((current) => {
      const i = LANG_CODES.indexOf(current);
      const next = LANG_CODES[(i + 1) % LANG_CODES.length] as Lang;
      localStorage.setItem(STORAGE_KEY, next);
      document.documentElement.lang = next;
      return next;
    });
  }, []);

  const t = useCallback(
    (key: TranslationKey): string =>
      translations[lang]?.[key] ?? translations.en[key] ?? (key as string),
    [lang],
  );

  return (
    <I18nContext.Provider value={{ lang, setLang, toggleLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}
