'use client';

import Link from 'next/link';
import { ShieldAlert } from 'lucide-react';
import { I18nText } from '../../i18n/provider';

export default function ForbiddenPage() {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-xl flex-col items-center justify-center text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-100 text-amber-800">
        <ShieldAlert size={28} aria-hidden="true" />
      </span>
      <h1 className="mt-5 text-3xl font-semibold tracking-tight text-[#292623]"><I18nText>没有访问权限</I18nText></h1>
      <p className="mt-3 text-sm leading-6 text-[#77716A]"><I18nText>当前账户没有访问此页面所需的权限。如需开通，请联系管理员。</I18nText></p>
      <Link href="/" className="mt-6 inline-flex h-11 items-center rounded-xl bg-[#EF4D2F] px-5 text-sm font-semibold text-white transition hover:bg-[#D94328]">
        <I18nText>返回首页</I18nText>
      </Link>
    </div>
  );
}
