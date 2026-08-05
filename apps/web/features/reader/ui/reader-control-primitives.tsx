'use client';

import type { LucideIcon } from 'lucide-react';
import type { MouseEvent, ReactNode } from 'react';
import { cn } from '../../../components/ui/cn';

type ReaderControlNavButtonProps = {
  icon: LucideIcon;
  label: string;
  ariaLabel?: string;
  active?: boolean;
  selected?: boolean;
  expanded?: boolean;
  panelTrigger?: string;
  disabled?: boolean;
  layout?: 'dock' | 'navigation';
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
  dark: boolean;
  className?: string;
};

export function ReaderControlNavButton({ icon: Icon, label, ariaLabel, active = false, selected = false, expanded, panelTrigger, disabled = false, layout = 'navigation', onClick, dark, className }: ReaderControlNavButtonProps) {
  return (
    <button
      type="button"
      aria-label={ariaLabel ?? label}
      aria-pressed={active || undefined}
      aria-expanded={expanded}
      aria-controls={expanded ? 'reader-panel' : undefined}
      data-reader-panel-trigger={panelTrigger}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'group flex min-w-0 flex-1 rounded-2xl font-medium transition active:scale-[0.97] disabled:pointer-events-none disabled:opacity-35',
        layout === 'dock' ? 'p-1.5 text-[11px] md:w-[4.75rem] md:flex-none' : 'p-1 text-xs',
        selected ? dark ? 'text-amber-400' : 'text-amber-700' : active ? 'text-amber-600' : '',
        className
      )}
    >
      <span
        data-reader-dock-surface="true"
        data-reader-dock-selection-surface={selected ? 'true' : undefined}
        className={cn(
          'flex h-full min-w-0 w-full flex-col items-center justify-center gap-1 px-1 transition-colors',
          layout === 'dock' ? 'rounded-[0.95rem]' : 'rounded-2xl',
          selected
            ? dark ? 'bg-amber-400/10 text-amber-300' : 'bg-amber-700/10 text-amber-700'
            : dark ? 'group-hover:bg-white/10' : 'group-hover:bg-stone-900/5'
        )}
      >
        <Icon size={layout === 'dock' ? 19 : 20} strokeWidth={1.8} fill={active ? 'currentColor' : 'none'} />
        <span className="max-w-full truncate">{label}</span>
      </span>
    </button>
  );
}

type ReaderQuickActionButtonProps = {
  label: string;
  ariaLabel?: string;
  selected?: boolean;
  expanded?: boolean;
  panelTrigger?: string;
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
  dark: boolean;
  children: ReactNode;
};

export function ReaderQuickActionButton({ label, ariaLabel, selected = false, expanded, panelTrigger, onClick, dark, children }: ReaderQuickActionButtonProps) {
  return (
    <button
      type="button"
      aria-label={ariaLabel ?? label}
      aria-expanded={expanded}
      aria-controls={expanded ? 'reader-panel' : undefined}
      data-reader-panel-trigger={panelTrigger}
      onClick={onClick}
      className={cn(
        'flex min-h-[4.5rem] min-w-0 flex-col items-center justify-center gap-1 rounded-2xl border px-1 text-xs font-medium transition active:scale-[0.97]',
        selected
          ? dark ? 'border-amber-400/25 bg-amber-400/10 text-amber-300' : 'border-amber-700/20 bg-amber-700/10 text-amber-800'
          : dark ? 'border-white/15 bg-white/[0.045] hover:bg-white/[0.09]' : 'border-stone-900/15 bg-white/55 hover:bg-white/80'
      )}
    >
      {children}
      <span className="max-w-full truncate">{label}</span>
    </button>
  );
}

type ReaderSegmentedControlProps<T extends string> = {
  ariaLabel: string;
  value: T;
  options: ReadonlyArray<{ value: T; label: string; icon?: LucideIcon; ariaLabel?: string }>;
  onChange: (value: T) => void;
  dark: boolean;
  disabled?: boolean;
  className?: string;
  behavior?: 'choice' | 'tabs';
};

export function ReaderSegmentedControl<T extends string>({ ariaLabel, value, options, onChange, dark, disabled = false, className, behavior = 'choice' }: ReaderSegmentedControlProps<T>) {
  return (
    <div
      role={behavior === 'tabs' ? 'tablist' : 'group'}
      aria-label={ariaLabel}
      aria-disabled={disabled}
      className={cn('grid min-w-0 gap-1 rounded-xl border p-1', dark ? 'border-white/10 bg-white/[0.07]' : 'border-stone-900/[0.07] bg-stone-900/[0.055]', disabled && 'opacity-45', className)}
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      {options.map((option) => {
        const Icon = option.icon;
        const selected = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role={behavior === 'tabs' ? 'tab' : undefined}
            aria-label={option.ariaLabel ?? option.label}
            aria-pressed={behavior === 'choice' ? selected : undefined}
            aria-selected={behavior === 'tabs' ? selected : undefined}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              'flex min-h-9 min-w-0 items-center justify-center gap-1 rounded-lg px-1 text-xs font-medium transition active:scale-[0.97]',
              selected
                ? dark ? 'bg-white/15 text-amber-300 shadow-sm' : 'bg-white text-amber-800 shadow-sm'
                : dark ? 'opacity-65 hover:bg-white/[0.07] hover:opacity-100' : 'opacity-60 hover:bg-white/55 hover:opacity-100'
            )}
          >
            {Icon ? <Icon size={15} strokeWidth={1.8} /> : null}
            <span className="truncate">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
