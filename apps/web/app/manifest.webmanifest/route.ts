import { NextResponse } from 'next/server';
import { getRequestLocale } from '../../i18n/server';
import { buildWebManifest } from '../../lib/pwa/manifest';

export const dynamic = 'force-dynamic';

export function GET() {
  const locale = getRequestLocale();
  return NextResponse.json(buildWebManifest(locale), {
    headers: {
      'Cache-Control': 'private, no-store',
      'Content-Language': locale,
      'Content-Type': 'application/manifest+json'
    }
  });
}
