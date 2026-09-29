'use client';

import { Lightbulb, MessageCircleWarning } from 'lucide-react';
import { useState } from 'react';
import { useI18n } from '../../../i18n/provider';
import { type FeedbackKind } from '../api';
import { FeedbackDialog } from './feedback-dialog';

export function AboutFeedbackEntry() {
  const { t } = useI18n();
  const [kind, setKind] = useState<FeedbackKind | null>(null);
  return <section className="mt-8 border-t border-[#DEDAD4] pt-7" aria-labelledby="feedback-entry-title">
    <h3 id="feedback-entry-title" className="text-lg font-semibold text-[#2A2825]">{t('反馈与报错')}</h3>
    <p className="mt-2 text-sm text-[#716B64]">{t('分享功能想法，或描述遇到的问题。')}</p>
    <div className="mt-4 grid gap-3 sm:grid-cols-2">
      <button type="button" onClick={() => setKind('suggestion')} className="flex min-h-14 items-center gap-3 rounded-2xl border border-[#DEDAD4] bg-white px-4 text-left text-sm font-medium text-[#34312E] transition hover:border-[#ED4D2D] hover:text-[#ED4D2D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#ED4D2D]"><Lightbulb size={19} />{t('功能建议')}</button>
      <button type="button" onClick={() => setKind('issue')} className="flex min-h-14 items-center gap-3 rounded-2xl border border-[#DEDAD4] bg-white px-4 text-left text-sm font-medium text-[#34312E] transition hover:border-[#ED4D2D] hover:text-[#ED4D2D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#ED4D2D]"><MessageCircleWarning size={19} />{t('报告问题')}</button>
    </div>
    {kind ? <FeedbackDialog initialKind={kind} onClose={() => setKind(null)} /> : null}
  </section>;
}
