import type { ReactNode } from 'react';
import { I18nText } from '../../i18n/provider';
import { cn } from './cn';

export type BadgeTone = 'slate' | 'blue' | 'green' | 'amber' | 'red';

const tones: Record<BadgeTone, string> = {
  slate: 'bg-slate-100 text-slate-600 border-slate-200',
  blue: 'bg-[#fff0ea] text-[#d94322] border-[#f8d0c4]',
  green: 'bg-emerald-50 text-emerald-700 border-emerald-100',
  amber: 'bg-amber-50 text-amber-700 border-amber-100',
  red: 'bg-red-50 text-red-700 border-red-100'
};

export function Badge({
  children,
  tone = 'slate',
  className,
  translate = true
}: {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
  translate?: boolean;
}) {
  return (
    <span
      data-i18n-skip={translate ? undefined : ''}
      className={cn('inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium', tones[tone], className)}
    >
      {translate && typeof children === 'string' ? <I18nText>{children}</I18nText> : children}
    </span>
  );
}
