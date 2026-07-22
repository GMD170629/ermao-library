'use client';

import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { Button } from './button';
import { cn } from './cn';

type ToastTone = 'success' | 'error' | 'info';

type Toast = {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
};

type ConfirmOptions = {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'default' | 'danger';
  confirmationText?: string;
};

type FeedbackContextValue = {
  toast: (toast: Omit<Toast, 'id'>) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
  confirm: (options: ConfirmOptions) => Promise<boolean>;
};

const FeedbackContext = createContext<FeedbackContextValue | null>(null);

const toastTone = {
  success: {
    icon: CheckCircle2,
    className: 'border-emerald-100 bg-emerald-50 text-emerald-800',
    iconClassName: 'text-emerald-600'
  },
  error: {
    icon: AlertTriangle,
    className: 'border-red-100 bg-red-50 text-red-800',
    iconClassName: 'text-red-600'
  },
  info: {
    icon: Info,
    className: 'border-blue-100 bg-blue-50 text-blue-800',
    iconClassName: 'text-blue-600'
  }
};

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [confirmOptions, setConfirmOptions] = useState<ConfirmOptions | null>(null);
  const [confirmInput, setConfirmInput] = useState('');
  const confirmResolver = useRef<((confirmed: boolean) => void) | null>(null);
  const nextToastId = useRef(1);

  const removeToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const toast = useCallback((next: Omit<Toast, 'id'>) => {
    const id = nextToastId.current++;
    setToasts((current) => [...current.slice(-3), { ...next, id }]);
    window.setTimeout(() => removeToast(id), next.tone === 'error' ? 6200 : 4200);
  }, [removeToast]);

  const closeConfirm = useCallback((confirmed: boolean) => {
    confirmResolver.current?.(confirmed);
    confirmResolver.current = null;
    setConfirmOptions(null);
    setConfirmInput('');
  }, []);

  const value = useMemo<FeedbackContextValue>(() => ({
    toast,
    success: (title, description) => toast({ tone: 'success', title, description }),
    error: (title, description) => toast({ tone: 'error', title, description }),
    info: (title, description) => toast({ tone: 'info', title, description }),
    confirm: (options) => new Promise<boolean>((resolve) => {
      confirmResolver.current?.(false);
      confirmResolver.current = resolve;
      setConfirmInput('');
      setConfirmOptions(options);
    })
  }), [toast]);

  const confirmationMatches = !confirmOptions?.confirmationText || confirmInput === confirmOptions.confirmationText;

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <div className="shuku-toast-region fixed right-4 top-4 z-[120] flex w-[calc(100vw-2rem)] max-w-sm flex-col gap-3 md:right-6 md:top-6" aria-live="polite" aria-atomic="true">
        {toasts.map((item) => {
          const tone = toastTone[item.tone];
          const Icon = tone.icon;
          return (
            <div key={item.id} className={cn('flex gap-3 rounded-2xl border p-4 shadow-xl backdrop-blur', tone.className)}>
              <Icon size={18} className={cn('mt-0.5 shrink-0', tone.iconClassName)} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">{item.title}</div>
                {item.description ? <div className="mt-1 text-sm opacity-80">{item.description}</div> : null}
              </div>
              <button type="button" onClick={() => removeToast(item.id)} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition hover:bg-white/60" aria-label="关闭提示">
                <X size={15} />
              </button>
            </div>
          );
        })}
      </div>
      {confirmOptions ? (
        <div className="fixed inset-0 z-[130] flex items-end justify-center bg-slate-950/45 p-0 backdrop-blur-sm md:items-center md:p-6" role="dialog" aria-modal="true" aria-label={confirmOptions.title}>
          <div className="w-full max-w-md rounded-t-3xl border border-slate-200 bg-white p-5 shadow-2xl md:rounded-3xl">
            <div className="flex items-start gap-3">
              <div className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl', confirmOptions.tone === 'danger' ? 'bg-red-50 text-red-600' : 'bg-blue-50 text-blue-600')}>
                {confirmOptions.tone === 'danger' ? <AlertTriangle size={20} /> : <Info size={20} />}
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-semibold text-slate-950">{confirmOptions.title}</h2>
                {confirmOptions.description ? <p className="mt-2 text-sm leading-6 text-slate-600">{confirmOptions.description}</p> : null}
              </div>
            </div>
            {confirmOptions.confirmationText ? (
              <label className="mt-5 block text-sm text-slate-600">
                请输入 {confirmOptions.confirmationText} 确认
                <input
                  value={confirmInput}
                  onChange={(event) => setConfirmInput(event.target.value)}
                  className="mt-2 h-11 w-full rounded-2xl border border-slate-200 px-4 text-slate-900 outline-none focus:border-blue-300 focus:ring-4 focus:ring-blue-100"
                  autoFocus
                />
              </label>
            ) : null}
            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="secondary" onClick={() => closeConfirm(false)}>{confirmOptions.cancelLabel ?? '取消'}</Button>
              <Button type="button" variant={confirmOptions.tone === 'danger' ? 'danger' : 'primary'} disabled={!confirmationMatches} onClick={() => closeConfirm(true)}>
                {confirmOptions.confirmLabel ?? '确认'}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </FeedbackContext.Provider>
  );
}

export function useToast() {
  const context = useContext(FeedbackContext);
  if (!context) throw new Error('useToast must be used inside FeedbackProvider');
  return context;
}

export function useConfirm() {
  const context = useContext(FeedbackContext);
  if (!context) throw new Error('useConfirm must be used inside FeedbackProvider');
  return context.confirm;
}
