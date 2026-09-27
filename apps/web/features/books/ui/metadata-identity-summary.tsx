import { I18nText, useI18n } from '../../../i18n/provider';
import type { MetadataIdentity } from '../model/book-contents';

export function MetadataIdentitySummary({ originalTitle, originalAuthor, identity, query }: Readonly<{
  originalTitle: string;
  originalAuthor: string | null;
  identity: MetadataIdentity;
  query: string;
}>) {
  const { t } = useI18n();
  return <div className="mx-5 mt-4 rounded-xl border border-blue-100 bg-blue-50 p-3 text-sm">
    <p className="font-medium"><I18nText>AI 标题作者分析</I18nText></p>
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
      <dt><I18nText>标题</I18nText></dt><dd data-i18n-skip>{originalTitle} → {identity.title ?? t('无法确定')}</dd>
      <dt><I18nText>作者</I18nText></dt><dd data-i18n-skip>{originalAuthor || t('未填写')} → {identity.author ?? t('无法确定')}</dd>
      <dt><I18nText>实际查询</I18nText></dt><dd data-i18n-skip>{query}</dd>
    </dl>
    {identity.needsReview ? <p className="mt-2 text-amber-800"><I18nText>结果不确定，请核对后应用。</I18nText></p> : null}
    <p className="mt-1 text-slate-600" data-i18n-skip>{identity.reason === 'AI 服务地址或模型未配置' ? t('AI 服务地址或模型未配置') : identity.reason}</p>
  </div>;
}
