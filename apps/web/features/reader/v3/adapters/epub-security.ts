export const EPUB_CONTENT_SECURITY_POLICY = [
  "default-src 'none'",
  "script-src 'none'",
  "connect-src 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
  "img-src 'self' blob: data:",
  "media-src 'self' blob: data:",
  "font-src 'self' blob: data:",
  "style-src 'unsafe-inline' blob:"
].join('; ');

const executableSelector = [
  'script',
  'iframe',
  'frame',
  'frameset',
  'object',
  'embed',
  'applet',
  'form',
  'input',
  'button',
  'textarea',
  'select',
  'meta[http-equiv]',
  'base'
].join(',');

const urlAttributes = new Set(['href', 'src', 'xlink:href', 'formaction', 'action', 'data', 'poster', 'srcset']);
const executableElementPattern = /<\s*(script|iframe|frame|frameset|object|embed|applet|form|button|textarea|select)\b[^>]*(?:\/\s*>|>[\s\S]*?<\s*\/\s*\1\s*>)/gi;
const standaloneExecutablePattern = /<\s*(input|base|meta\b[^>]*http-equiv)[^>]*\/?\s*>/gi;
const eventAttributePattern = /\s+on[a-z0-9_-]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+)/gi;
const srcdocAttributePattern = /\s+srcdoc\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+)/gi;
const dangerousUrlAttributePattern = /\s+(href|src|xlink:href|formaction|action|data|poster|srcset)\s*=\s*(?:"\s*(?:javascript|vbscript|data\s*:\s*text\/html)[^"]*"|'\s*(?:javascript|vbscript|data\s*:\s*text\/html)[^']*'|\s*(?:javascript|vbscript|data\s*:\s*text\/html)[^\s"'=<>`]*)/gi;
const activeStylePattern = /(?:expression\s*\(|behavior\s*:|-moz-binding\s*:|url\s*\(\s*["']?\s*(?:javascript|vbscript)\s*:)/i;
const readerOwnedStyleProperties = new Set([
  'color',
  '-webkit-text-fill-color',
  'background',
  'background-color',
  'background-image',
  'font',
  'font-family',
  'line-height'
]);

function isDangerousUrl(value: string) {
  const normalized = value.replace(/[\u0000-\u0020]+/g, '').toLowerCase();
  return normalized.startsWith('javascript:')
    || normalized.startsWith('vbscript:')
    || normalized.startsWith('data:text/html');
}

function isRemoteResourceAttribute(element: Element, name: string, value: string) {
  if (!['href', 'src', 'xlink:href', 'poster', 'srcset'].includes(name)) return false;
  if (element.localName.toLowerCase() === 'a' && name === 'href') return false;
  return /^(?:https?:)?\/\//i.test(value.trim());
}

export function sanitizeEpubDocument(document: Document) {
  document.querySelectorAll(executableSelector).forEach((element) => element.remove());
  document.querySelectorAll('*').forEach((element) => {
    Array.from(element.attributes).forEach((attribute) => {
      const name = attribute.name.toLowerCase();
      const value = attribute.value;
      if (name === 'style') {
        if (activeStylePattern.test(value)) {
          element.removeAttribute(attribute.name);
        } else {
          const declaration = (element as HTMLElement | SVGElement).style;
          Array.from(declaration).forEach((property) => {
            if (readerOwnedStyleProperties.has(property.toLowerCase())) declaration.removeProperty(property);
          });
          if (!declaration.cssText.trim()) element.removeAttribute(attribute.name);
        }
        return;
      }
      if (
        name.startsWith('on')
        || name === 'srcdoc'
        || (urlAttributes.has(name) && isDangerousUrl(value))
        || isRemoteResourceAttribute(element, name, value)
      ) {
        element.removeAttribute(attribute.name);
      }
    });

    if (element.localName.toLowerCase() === 'a') {
      const href = element.getAttribute('href')?.trim() ?? '';
      if (/^https?:\/\//i.test(href)) {
        element.setAttribute('rel', 'noopener noreferrer');
        element.setAttribute('target', '_blank');
      }
    }
  });

  let head = document.head ?? document.querySelector('head');
  if (!head && document.documentElement?.localName.toLowerCase() === 'html') {
    const namespace = document.documentElement.namespaceURI;
    head = namespace
      ? document.createElementNS(namespace, 'head') as HTMLHeadElement
      : document.createElement('head');
    document.documentElement.prepend(head);
  }
  if (head && !head.querySelector('meta[data-shuku-epub-csp="true"]')) {
    const namespace = document.documentElement.namespaceURI;
    const meta = namespace
      ? document.createElementNS(namespace, 'meta') as HTMLMetaElement
      : document.createElement('meta');
    meta.setAttribute('http-equiv', 'Content-Security-Policy');
    meta.setAttribute('content', EPUB_CONTENT_SECURITY_POLICY);
    meta.setAttribute('data-shuku-epub-csp', 'true');
    head.prepend(meta);
  }
}

/**
 * Applies only the structural portion of sanitization that can affect CFI node
 * paths. Attribute and CSP hardening are deferred until rendition loading.
 */
export function sanitizeEpubDocumentForLocationIndex(document: Document) {
  document.querySelectorAll(executableSelector).forEach((element) => element.remove());
  if (!document.head && !document.querySelector('head') && document.documentElement?.localName.toLowerCase() === 'html') {
    const namespace = document.documentElement.namespaceURI;
    const head = namespace
      ? document.createElementNS(namespace, 'head')
      : document.createElement('head');
    document.documentElement.prepend(head);
  }
}

export function sanitizeEpubMarkupFallback(markup: string) {
  return markup
    .replace(executableElementPattern, '')
    .replace(standaloneExecutablePattern, '')
    .replace(eventAttributePattern, '')
    .replace(srcdocAttributePattern, '')
    .replace(dangerousUrlAttributePattern, '')
    .replace(/\s+style\s*=\s*"([^"]*)"/gi, (match, style: string) => activeStylePattern.test(style) ? '' : match)
    .replace(/\s+style\s*=\s*'([^']*)'/gi, (match, style: string) => activeStylePattern.test(style) ? '' : match);
}

function malformedEpubMarkup() {
  return `<?xml version="1.0" encoding="UTF-8"?>
    <html xmlns="http://www.w3.org/1999/xhtml">
      <head>
        <meta http-equiv="Content-Security-Policy" content="${EPUB_CONTENT_SECURITY_POLICY}" data-shuku-epub-csp="true" />
        <title>章节格式错误</title>
      </head>
      <body><p>此章节格式损坏，已停止显示以保护阅读安全。</p></body>
    </html>`;
}

export function sanitizeEpubMarkup(markup: string) {
  if (typeof DOMParser === 'undefined' || typeof XMLSerializer === 'undefined') {
    return malformedEpubMarkup();
  }

  try {
    const document = new DOMParser().parseFromString(markup, 'application/xhtml+xml');
    if (document.querySelector('parsererror')) return malformedEpubMarkup();
    sanitizeEpubDocument(document);
    return new XMLSerializer().serializeToString(document);
  } catch {
    return malformedEpubMarkup();
  }
}

export function hardenEpubIframe(iframe: HTMLIFrameElement | undefined) {
  if (!iframe) return;
  // WebKit suppresses even host-registered DOM callbacks when allow-scripts is
  // absent. Book code remains non-executable because serialization strips it
  // and the initial document CSP keeps script-src at 'none'.
  iframe.setAttribute('sandbox', 'allow-same-origin allow-scripts');
  iframe.setAttribute('referrerpolicy', 'no-referrer');
}
