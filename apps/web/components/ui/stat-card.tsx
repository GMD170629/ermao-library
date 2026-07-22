import type { LucideIcon } from 'lucide-react';
import { cn } from './cn';

type Tone = 'blue' | 'green' | 'amber' | 'slate';

const colors: Record<Tone, string> = {
  blue: 'bg-blue-50 text-blue-700',
  green: 'bg-emerald-50 text-emerald-700',
  amber: 'bg-amber-50 text-amber-700',
  slate: 'bg-slate-100 text-slate-700'
};

export function StatCard({
  icon: Icon,
  label,
  value,
  hint,
  tone = 'blue'
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  hint: string;
  tone?: Tone;
}) {
  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div className={cn('flex h-10 w-10 items-center justify-center rounded-2xl', colors[tone])}>
          <Icon size={20} />
        </div>
        <span className="text-xs text-slate-400">{hint}</span>
      </div>
      <div className="mt-4 text-2xl font-semibold tracking-tight text-slate-950">{value}</div>
      <div className="mt-1 text-sm text-slate-500">{label}</div>
    </div>
  );
}
