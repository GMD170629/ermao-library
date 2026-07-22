import { cn } from './cn';

type ProgressProps = {
  value: number;
  className?: string;
};

export function Progress({ value, className = '' }: ProgressProps) {
  const clampedValue = Math.max(0, Math.min(100, value));

  return (
    <div className={cn('h-2 overflow-hidden rounded-full bg-[#e7e2dc]', className)}>
      <div className="h-full rounded-full bg-[#ff4f2a]" style={{ width: `${clampedValue}%` }} />
    </div>
  );
}
