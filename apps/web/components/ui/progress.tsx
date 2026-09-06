import { cn } from './cn';

type ProgressProps = {
  value: number;
  className?: string;
};

export function Progress({ value, className = '' }: ProgressProps) {
  const clampedValue = Math.max(0, Math.min(100, value));

  return (
    <div className={cn('h-2 overflow-hidden rounded-full bg-[var(--visual-color-app-divider)]', className)}>
      <div className="h-full rounded-full bg-[var(--visual-color-app-brand-accent)]" style={{ width: `${clampedValue}%` }} />
    </div>
  );
}
