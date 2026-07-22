import type { ReactNode } from 'react';
import { MobileNavigationTrigger } from '../layout/mobile-navigation';

export function PageTitle({ title, desc, action }: { title: string; desc: string; action?: ReactNode }) {
  return (
    <div className="flex items-start gap-3 sm:gap-4">
      <MobileNavigationTrigger className="mt-0.5" />
      <div className="flex min-w-0 flex-1 flex-col items-stretch gap-4 sm:flex-row sm:items-end sm:justify-between sm:gap-6">
        <div className="min-w-0">
          <h1 className="break-words text-[32px] font-semibold leading-[1.14] tracking-[-0.035em] text-[#17191d] sm:text-[34px]">{title}</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[#77736f] sm:text-base">{desc}</p>
        </div>
        {action ? <div className="flex max-w-full flex-wrap items-center gap-2 sm:w-auto sm:shrink-0 sm:justify-end">{action}</div> : null}
      </div>
    </div>
  );
}
