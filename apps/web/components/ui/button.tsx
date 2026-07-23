'use client';

import { Loader2 } from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { useI18n } from '../../i18n/provider';
import { cn } from './cn';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-[#ff4f2a] text-white hover:bg-[#e94320]',
  secondary: 'border border-[#ded8d1] bg-white text-[#4f4b47] hover:border-[#f2b7a6] hover:bg-[#fff5f1] hover:text-[#d94322]',
  ghost: 'bg-transparent text-[#6f6a65] hover:bg-[#f1eeea] hover:text-[#17191d]',
  danger: 'border border-red-100 bg-red-50 text-red-700 hover:border-red-200 hover:bg-red-100 hover:text-red-800'
};

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children?: ReactNode;
  icon?: LucideIcon;
  loading?: boolean;
  loadingText?: string;
  variant?: ButtonVariant;
};

export function Button({ children, icon: Icon, loading = false, loadingText, variant = 'primary', className = '', disabled, ...props }: ButtonProps) {
  const { t } = useI18n();
  return (
    <button
      className={cn(
        'inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-[12px] px-4 py-2.5 text-sm font-medium leading-5 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ffc9b9] disabled:cursor-not-allowed disabled:opacity-60 data-[loading=true]:opacity-100',
        variants[variant],
        className
      )}
      data-loading={loading ? 'true' : undefined}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <Loader2 size={16} className="shrink-0 animate-spin" strokeWidth={2.4} /> : Icon ? <Icon size={16} className="shrink-0" strokeWidth={2.2} /> : null}
      {loading && loadingText ? t(loadingText) : typeof children === 'string' ? t(children) : children}
    </button>
  );
}
