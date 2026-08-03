'use client';

import { ExternalLink, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Cover } from '../../components/book/cover';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { PageTitle } from '../../components/ui/page-title';
import { useI18n } from '../../i18n/provider';
import { normalizeOrganizeJob, organizeStatusCategory, organizeStatusLabel, type OrganizeJobView } from './organize-page';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

type JobResponse = {
  ok: boolean;
  data?: { job: OrganizeJobView };
  error?: { message: string };
};

function valueLabel(value: unknown) {
  if (Array.isArray(value)) return value.join(', ');
  if (value === null || value === undefined || value === '') return '未填写';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function metadataChecks(job: OrganizeJobView) {
  const book = job.book;
  const volumes = book.mediaVersions.flatMap((mediaVersion) => mediaVersion.volumes);
  const publishedAt = volumes.map((volume) => volume.publishedAt).find(Boolean) ?? null;
  return [
    { key: 'title', label: '标题', complete: Boolean(book.title.trim()), value: book.title },
    { key: 'author', label: '作者', complete: Boolean(book.author.trim() && book.author !== '未知作者'), value: book.author },
    { key: 'cover', label: '封面', complete: Boolean(book.coverUrl && book.coverStatus === 'READY'), value: book.coverStatus === 'READY' ? '已生成' : '缺少或待生成' },
    { key: 'seriesName', label: '系列', complete: Boolean(book.seriesName), value: book.seriesName },
    { key: 'seriesIndex', label: '卷号', complete: book.seriesIndex !== null, value: book.seriesIndex },
    { key: 'publishedAt', label: '出版时间', complete: publishedAt !== null, value: publishedAt },
    { key: 'tags', label: '标签', complete: book.tags.length > 0, value: book.tags },
    { key: 'description', label: '简介', complete: Boolean(book.description), value: book.description }
  ];
}

export function OrganizeJobDetailPage({ jobId, embedded = false }: { jobId: string; embedded?: boolean; returnPath?: string }) {
  const { t: i18nAttribute } = useAttributeI18n();
  const router = useRouter();
  const { locale } = useI18n();
  const [job, setJob] = useState<OrganizeJobView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadJob = useCallback(() => {
    setLoading(true);
    fetch(`/api/organize/jobs/${jobId}`)
      .then((response) => response.json() as Promise<JobResponse>)
      .then((payload) => {
        if (!payload.ok || !payload.data?.job) throw new Error(payload.error?.message ?? '读取整理任务失败');
        const nextJob = normalizeOrganizeJob(payload.data.job);
        if (!nextJob) throw new Error('整理任务缺少读物信息');
        setJob(nextJob);
        setError('');
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : '读取整理任务失败'))
      .finally(() => setLoading(false));
  }, [jobId]);

  useEffect(() => {
    loadJob();
  }, [loadJob]);

  const checks = useMemo(() => (job ? metadataChecks(job) : []), [job]);

  if (loading) return <div className="shuku-loading-panel p-8 text-sm" role="status" aria-live="polite"><I18nText>正在读取整理任务...</I18nText></div>;
  if (!job) return <div className="rounded-3xl border border-red-100 bg-red-50 p-8 text-sm text-red-700">{error || i18nAttribute("整理任务不存在")}</div>;

  return (
    <div className={embedded ? 'space-y-5' : 'space-y-6'}>
      {!embedded ? <PageTitle
        title={i18nAttribute("整理详情")}
        desc={i18nAttribute("查看本次识别的状态、数据源和元数据完整度。")}
        action={<Button variant="secondary" icon={RefreshCw} onClick={loadJob}><I18nText>刷新</I18nText></Button>}
      /> : (
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" icon={RefreshCw} onClick={loadJob}><I18nText>刷新</I18nText></Button>
        </div>
      )}

      {error ? <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <div className={embedded ? 'grid gap-5' : 'grid gap-5 lg:grid-cols-[320px_1fr]'}>
        <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex gap-4">
            <Cover book={job.book} className="h-40 w-28" />
            <div data-i18n-skip className="min-w-0">
              <h2 className="line-clamp-2 text-lg font-semibold text-slate-900">{job.book.title}</h2>
              <p className="mt-1 text-sm text-slate-500">{job.book.author} · {job.book.mediaVersions.flatMap((mediaVersion) => mediaVersion.volumes).map((volume) => volume.format).join(' / ')}</p>
              <div className="mt-3 flex flex-wrap gap-1">
                <Badge tone={job.statusCategory === 'SUCCESS' ? 'green' : job.statusCategory === 'FAILED' ? 'red' : job.statusCategory === 'RECOGNIZING' ? 'blue' : 'amber'}>{organizeStatusLabel(job.statusCategory ?? organizeStatusCategory(job.status, job.metadataLookupStatus))}</Badge>
                {!embedded ? <Badge tone={job.book.metadataQuality >= 80 ? 'green' : 'blue'}><I18nText>质量 </I18nText>{job.book.metadataQuality}</Badge> : null}
              </div>
            </div>
          </div>
          <dl className="mt-5 space-y-3 text-sm">
            <div><dt className="text-slate-500"><I18nText>文件路径</I18nText></dt><dd className="mt-1 break-all text-slate-800">{job.book.mediaVersions.flatMap((mediaVersion) => mediaVersion.volumes).flatMap((volume) => volume.files)[0]?.path || i18nAttribute("未记录")}</dd></div>
            <div><dt className="text-slate-500"><I18nText>导入时间</I18nText></dt><dd className="mt-1 text-slate-800">{new Date(job.book.addedAt).toLocaleString(locale)}</dd></div>
            <div><dt className="text-slate-500"><I18nText>任务更新时间</I18nText></dt><dd className="mt-1 text-slate-800">{new Date(job.updatedAt).toLocaleString(locale)}</dd></div>
            <div><dt className="text-slate-500"><I18nText>整理摘要</I18nText></dt><dd className="mt-1 text-slate-800">{job.summary ?? i18nAttribute("暂无整理摘要")}</dd></div>
          </dl>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button variant="secondary" icon={ExternalLink} onClick={() => router.push(`/works/${job.book.id}`)}><I18nText>打开读物详情</I18nText></Button>
          </div>
        </section>

        {!embedded ? <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold"><I18nText>缺失信息</I18nText></h2>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {checks.map((check) => (
              <div key={check.key} className="rounded-2xl border border-slate-200 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-slate-800">{check.label}</span>
                  <Badge tone={check.complete ? 'green' : 'amber'}>{check.complete ? i18nAttribute("已有") : i18nAttribute("缺失")}</Badge>
                </div>
                <div className="mt-2 line-clamp-2 text-xs text-slate-500">{valueLabel(check.value)}</div>
              </div>
            ))}
          </div>
        </section> : null}
      </div>

    </div>
  );
}
