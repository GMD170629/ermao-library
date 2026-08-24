'use client';

import type { LucideIcon } from 'lucide-react';
import { ChevronRight } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { cn } from './cn';

export type ContextMenuPosition = Readonly<{ x: number; y: number }>;

export type ContextActionMenuItem<Action extends string> = Readonly<{
  action: Action;
  label: string;
  description?: string;
  icon: LucideIcon;
  destructive?: boolean;
  disabled?: boolean;
  separatorBefore?: boolean;
  submenu?: readonly ContextActionMenuItem<Action>[];
}>;

export function ContextActionMenu<Action extends string>({
  position,
  ariaLabel,
  title,
  badge,
  items,
  footer,
  onClose,
  onSelect,
  returnFocusTo
}: {
  position: ContextMenuPosition | null;
  ariaLabel: string;
  title: string;
  badge?: string;
  items: readonly ContextActionMenuItem<Action>[];
  footer?: string;
  onClose: () => void;
  onSelect: (action: Action) => void;
  returnFocusTo?: HTMLElement | null;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [openSubmenuAction, setOpenSubmenuAction] = useState<Action | null>(null);

  useEffect(() => {
    if (!position) return;
    const focusableItems = () => Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[data-context-menu-level="root"]:not(:disabled)') ?? []);
    const frame = window.requestAnimationFrame(() => focusableItems()[0]?.focus());
    function closeOnPointer(event: MouseEvent) {
      if (!menuRef.current?.contains(event.target as Node)) onClose();
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        returnFocusTo?.focus();
        return;
      }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp' && event.key !== 'Home' && event.key !== 'End') return;
      const buttons = focusableItems();
      if (!buttons.length) return;
      event.preventDefault();
      const currentIndex = buttons.indexOf(document.activeElement as HTMLButtonElement);
      if (event.key === 'Home') buttons[0]?.focus();
      else if (event.key === 'End') buttons.at(-1)?.focus();
      else {
        const direction = event.key === 'ArrowDown' ? 1 : -1;
        const nextIndex = currentIndex < 0 ? 0 : (currentIndex + direction + buttons.length) % buttons.length;
        buttons[nextIndex]?.focus();
      }
    }
    function closeOnViewportChange() {
      onClose();
    }
    document.addEventListener('mousedown', closeOnPointer);
    document.addEventListener('keydown', handleKey);
    window.addEventListener('resize', closeOnViewportChange);
    window.addEventListener('scroll', closeOnViewportChange, true);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('mousedown', closeOnPointer);
      document.removeEventListener('keydown', handleKey);
      window.removeEventListener('resize', closeOnViewportChange);
      window.removeEventListener('scroll', closeOnViewportChange, true);
    };
  }, [onClose, position, returnFocusTo]);

  useEffect(() => {
    setOpenSubmenuAction(null);
  }, [position]);

  if (!position || typeof document === 'undefined') return null;
  const width = 316;
  const estimatedHeight = Math.min(window.innerHeight - 24, 88 + items.length * 58 + (footer ? 48 : 0));
  const left = Math.max(12, Math.min(position.x, window.innerWidth - width - 12));
  const top = Math.max(12, Math.min(position.y, window.innerHeight - estimatedHeight - 12));

  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      aria-label={ariaLabel}
      style={{ left, top, width, maxHeight: 'calc(100vh - 24px)' }}
      className="fixed z-[130] rounded-2xl border border-black/[0.1] bg-[#FFFEFC] p-2 shadow-[0_22px_70px_rgba(47,37,31,0.24)]"
    >
      <div className="flex items-center justify-between gap-3 px-3 pb-2 pt-1.5">
        <span className="truncate text-xs font-semibold text-[#625C56]">{title}</span>
        {badge ? <span className="shrink-0 rounded-full bg-[#FFF0EA] px-2 py-1 text-[11px] font-medium text-[#D7462B]">{badge}</span> : null}
      </div>
      <div className="space-y-0.5">
        {items.map((item) => {
          const Icon = item.icon;
          const submenuOpen = item.submenu && openSubmenuAction === item.action;
          const submenuOnLeft = left + width * 2 + 8 > window.innerWidth - 12;
          return <div key={item.action} className="relative" onMouseEnter={() => setOpenSubmenuAction(item.submenu ? item.action : null)}>
            {item.separatorBefore ? <div className="my-1.5 h-px bg-black/[0.06]" /> : null}
            <button
              type="button"
              role="menuitem"
              data-context-menu-level="root"
              disabled={item.disabled}
              aria-haspopup={item.submenu ? 'menu' : undefined}
              aria-expanded={item.submenu ? submenuOpen : undefined}
              onClick={() => item.submenu ? setOpenSubmenuAction(item.action) : onSelect(item.action)}
              className={cn(
                'group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left outline-none transition disabled:cursor-not-allowed disabled:opacity-40',
                item.destructive ? 'hover:bg-red-50 focus-visible:bg-red-50' : 'hover:bg-[#FFF2ED] focus-visible:bg-[#FFF2ED]'
              )}
            >
              <span className={cn(
                'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition group-hover:bg-white',
                item.destructive ? 'bg-red-50 text-red-600' : 'bg-black/[0.035] text-[#746D67] group-hover:text-[#EF4D2F]'
              )}>
                <Icon size={16} />
              </span>
              <span className="min-w-0 flex-1">
                <span className={cn('block text-sm font-medium leading-5', item.destructive ? 'text-red-700' : 'text-[#302C29]')}>{item.label}</span>
                {item.description ? <span className="block truncate text-[11px] leading-4 text-[#8B847D]">{item.description}</span> : null}
              </span>
              {item.submenu ? <ChevronRight size={15} className="ml-auto shrink-0 text-[#948D86]" /> : null}
            </button>
            {submenuOpen ? <div
              role="menu"
              aria-label={item.label}
              className={cn(
                'absolute top-0 z-10 w-56 rounded-2xl border border-black/[0.1] bg-[#FFFEFC] p-2 shadow-[0_22px_70px_rgba(47,37,31,0.24)]',
                submenuOnLeft ? 'right-[calc(100%+8px)]' : 'left-[calc(100%+8px)]'
              )}
            >
              {item.submenu?.map((subitem) => {
                const SubIcon = subitem.icon;
                return <button
                  key={subitem.action}
                  type="button"
                  role="menuitem"
                  disabled={subitem.disabled}
                  onClick={() => onSelect(subitem.action)}
                  className="group flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left outline-none transition hover:bg-[#FFF2ED] focus-visible:bg-[#FFF2ED] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-black/[0.035] text-[#746D67] transition group-hover:bg-white group-hover:text-[#EF4D2F]"><SubIcon size={16} /></span>
                  <span className="min-w-0 flex-1"><span className="block text-sm font-medium leading-5 text-[#302C29]">{subitem.label}</span>{subitem.description ? <span className="block truncate text-[11px] leading-4 text-[#8B847D]">{subitem.description}</span> : null}</span>
                </button>;
              })}
            </div> : null}
          </div>;
        })}
      </div>
      {footer ? <div className="mt-2 border-t border-black/[0.06] px-3 pt-2 text-[11px] leading-5 text-[#948D86]">{footer}</div> : null}
    </div>,
    document.body
  );
}
