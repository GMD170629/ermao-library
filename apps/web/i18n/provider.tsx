'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from 'react';
import { APP_BASE_PATH, withBasePath } from '../lib/base-path';
import {
  DEFAULT_LOCALE,
  LOCALE_COOKIE_MAX_AGE_SECONDS,
  LOCALE_COOKIE_NAME,
  LOCALE_STORAGE_KEY,
  normalizeLocale,
  type AppLocale
} from './config';
import { translateMessage, type MessageValues } from './messages';

type AppConfigPayload = {
  ok?: boolean;
  data?: {
    language?: unknown;
    supportedLocales?: unknown;
  };
};

type SessionLocalePayload = {
  ok?: boolean;
  data?: { user?: { locale?: unknown } };
};

export type I18nContextValue = {
  locale: AppLocale;
  setLocale: (locale: AppLocale) => void;
  t: (source: string, values?: MessageValues) => string;
  formatDate: (value: Date | string | number, options?: Intl.DateTimeFormatOptions) => string;
  formatDateTime: (value: Date | string | number, options?: Intl.DateTimeFormatOptions) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
  formatPercent: (value: number, options?: Intl.NumberFormatOptions) => string;
  formatRelativeTime: (value: number, unit: Intl.RelativeTimeFormatUnit) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);
const translatableAttributes = ['aria-label', 'aria-description', 'placeholder', 'title', 'alt'] as const;
const originalText = new WeakMap<Node, string>();
const originalAttributes = new WeakMap<Element, Map<string, string>>();

function cookiePath() {
  return APP_BASE_PATH || '/';
}

function persistLocaleCookie(locale: AppLocale) {
  document.cookie = [
    `${LOCALE_COOKIE_NAME}=${encodeURIComponent(locale)}`,
    `Path=${cookiePath()}`,
    `Max-Age=${LOCALE_COOKIE_MAX_AGE_SECONDS}`,
    'SameSite=Lax'
  ].join('; ');
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    // Cookies remain the durable source when storage is unavailable.
  }
}

function toDate(value: Date | string | number) {
  return value instanceof Date ? value : new Date(value);
}

function translateDomNode(root: ParentNode, locale: AppLocale) {
  const textWalker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let textNode = textWalker.nextNode();
  while (textNode) {
    const parent = textNode.parentElement;
    if (parent && !parent.closest('[data-i18n-skip]') && !['SCRIPT', 'STYLE', 'TEXTAREA'].includes(parent.tagName)) {
      const current = textNode.nodeValue ?? '';
      if (locale === 'zh-CN') {
        const source = originalText.get(textNode);
        if (source !== undefined && current !== source) textNode.nodeValue = source;
        originalText.delete(textNode);
      } else {
        const source = originalText.get(textNode) ?? current;
        const translated = translateMessage(locale, source);
        if (translated !== source) {
          originalText.set(textNode, source);
          if (translated !== current) textNode.nodeValue = translated;
        }
      }
    }
    textNode = textWalker.nextNode();
  }

  const elements = root instanceof Element
    ? [root, ...Array.from(root.querySelectorAll('*'))]
    : Array.from(root.querySelectorAll('*'));
  for (const element of elements) {
    if (element.closest('[data-i18n-skip]')) continue;
    for (const attribute of translatableAttributes) {
      const current = element.getAttribute(attribute);
      if (!current) continue;
      const savedAttributes = originalAttributes.get(element);
      if (locale === 'zh-CN') {
        const source = savedAttributes?.get(attribute);
        if (source !== undefined && current !== source) element.setAttribute(attribute, source);
        savedAttributes?.delete(attribute);
        continue;
      }
      const source = savedAttributes?.get(attribute) ?? current;
      const translated = translateMessage(locale, source);
      if (translated !== source) {
        const nextSavedAttributes = savedAttributes ?? new Map<string, string>();
        nextSavedAttributes.set(attribute, source);
        originalAttributes.set(element, nextSavedAttributes);
        if (translated !== current) element.setAttribute(attribute, translated);
      }
    }
  }
}

export function I18nProvider({
  initialLocale = DEFAULT_LOCALE,
  children
}: {
  initialLocale?: AppLocale;
  children: ReactNode;
}) {
  const [locale, updateLocale] = useState<AppLocale>(initialLocale);
  const localeRef = useRef(locale);

  const setLocale = useCallback((nextLocale: AppLocale) => {
    const normalized = normalizeLocale(nextLocale);
    localeRef.current = normalized;
    updateLocale(normalized);
    document.documentElement.lang = normalized;
    persistLocaleCookie(normalized);
  }, []);

  useEffect(() => {
    localeRef.current = locale;
    document.documentElement.lang = locale;
    persistLocaleCookie(locale);
  }, [locale]);

  useEffect(() => {
    function syncLocale(event: StorageEvent) {
      if (event.key !== LOCALE_STORAGE_KEY || !event.newValue) return;
      const nextLocale = normalizeLocale(event.newValue, localeRef.current);
      if (nextLocale !== localeRef.current) setLocale(nextLocale);
    }
    window.addEventListener('storage', syncLocale);
    return () => window.removeEventListener('storage', syncLocale);
  }, [setLocale]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetch(withBasePath('/api/app-config'), { cache: 'no-store', signal: controller.signal })
        .then((response) => response.json() as Promise<AppConfigPayload>)
        .catch(() => null),
      fetch(withBasePath('/api/auth/me'), {
        cache: 'no-store',
        credentials: 'same-origin',
        signal: controller.signal
      })
        .then((response) => response.json() as Promise<SessionLocalePayload>)
        .catch(() => null)
    ])
      .then(([configPayload, sessionPayload]) => {
        const preferred = sessionPayload?.ok
          ? sessionPayload.data?.user?.locale
          : configPayload?.ok
            ? configPayload.data?.language
            : localeRef.current;
        const configuredLocale = normalizeLocale(preferred, localeRef.current);
        if (configuredLocale !== localeRef.current) setLocale(configuredLocale);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [setLocale]);

  useEffect(() => {
    translateDomNode(document.body, locale);
    if (locale === 'zh-CN') return undefined;
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === 'characterData' && mutation.target.parentNode) {
          translateDomNode(mutation.target.parentNode, locale);
          continue;
        }
        for (const node of Array.from(mutation.addedNodes)) {
          if (node instanceof Element || node instanceof DocumentFragment) translateDomNode(node, locale);
          else if (node.parentNode) translateDomNode(node.parentNode, locale);
        }
        if (mutation.type === 'attributes' && mutation.target instanceof Element) {
          translateDomNode(mutation.target, locale);
        }
      }
    });
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: [...translatableAttributes],
      childList: true,
      characterData: true,
      subtree: true
    });
    return () => observer.disconnect();
  }, [locale]);

  const value = useMemo<I18nContextValue>(() => ({
    locale,
    setLocale,
    t: (source, values) => translateMessage(locale, source, values),
    formatDate: (input, options) => new Intl.DateTimeFormat(locale, options).format(toDate(input)),
    formatDateTime: (input, options) => new Intl.DateTimeFormat(locale, {
      dateStyle: 'medium',
      timeStyle: 'short',
      ...options
    }).format(toDate(input)),
    formatNumber: (input, options) => new Intl.NumberFormat(locale, options).format(input),
    formatPercent: (input, options) => new Intl.NumberFormat(locale, {
      style: 'percent',
      maximumFractionDigits: 0,
      ...options
    }).format(input),
    formatRelativeTime: (input, unit) => new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(input, unit)
  }), [locale, setLocale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) throw new Error('useI18n must be used within I18nProvider');
  return value;
}

export function I18nText({
  children,
  values
}: {
  children: string;
  values?: MessageValues;
}) {
  const { t } = useI18n();
  return t(children, values);
}
