import { BookOpen, ExternalLink, Github, Info, Layers3, Scale } from 'lucide-react';
import Image from 'next/image';
import rootPackage from '../../../../../package.json';
import { withBasePath } from '../../../lib/base-path';
import { PRODUCT_DESCRIPTION, PRODUCT_NAME } from '../../../lib/brand';
import { SettingsCenterShell } from './settings-center-shell';
import { I18nText } from '@/i18n/provider';

const PROJECT_URL = 'https://github.com/GMD170629/ermao-library';

const projectDetails = [
  { label: '运行方式', value: '自托管 Web 应用 / PWA', icon: Layers3 },
  { label: '支持格式', value: 'EPUB、漫画、PDF、文本与有声书', icon: BookOpen },
  { label: '开源许可', value: 'MIT License', icon: Scale }
];

export function AboutSettingsPage() {
  return (
    <SettingsCenterShell title="关于" description={`查看 ${PRODUCT_NAME} 的版本、项目地址与开源信息。`}>
      <div className="overflow-hidden rounded-[24px] border border-[#DEDAD4] bg-white">
        <div className="grid border-b border-[#DEDAD4] md:grid-cols-[minmax(0,1fr)_220px]">
          <div className="flex items-start gap-5 p-6 sm:p-8">
            <Image
              src={withBasePath('/icons/icon-192.png')}
              alt={`${PRODUCT_NAME} 应用图标`}
              width={76}
              height={76}
              className="h-[68px] w-[68px] shrink-0 rounded-[17px] border border-black/[0.06] sm:h-[76px] sm:w-[76px]"
              priority
            />
            <div className="min-w-0">
              <h3 className="text-2xl font-semibold tracking-[-0.03em] text-[#20201F] sm:text-[28px]">{PRODUCT_NAME}</h3>
              <p className="mt-2 max-w-xl text-sm leading-6 text-[#716B64]">{PRODUCT_DESCRIPTION}</p>
            </div>
          </div>
          <div className="flex items-center justify-between gap-4 border-t border-[#DEDAD4] bg-[#F7F5F2] px-6 py-5 md:block md:border-l md:border-t-0 md:px-7 md:py-7">
            <span className="text-xs font-medium uppercase tracking-[0.12em] text-[#827B73]"><I18nText>当前版本</I18nText></span>
            <strong className="font-mono text-2xl font-semibold tabular-nums tracking-[-0.03em] text-[#ED4D2D] md:mt-3 md:block md:text-[30px]">
              v{rootPackage.version}
            </strong>
          </div>
        </div>

        <div className="grid divide-y divide-[#E5E1DC] sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          {projectDetails.map(({ label, value, icon: Icon }) => (
            <div key={label} className="flex items-start gap-3 px-6 py-5">
              <Icon size={19} className="mt-0.5 shrink-0 text-[#ED4D2D]" strokeWidth={1.8} aria-hidden="true" />
              <div>
                <div className="text-xs text-[#827B73]"><I18nText>{label}</I18nText></div>
                <div className="mt-1 text-sm font-medium leading-6 text-[#2A2825]">{value}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <section className="mt-8 border-t border-[#DEDAD4] pt-7" aria-labelledby="project-introduction-title">
        <div className="flex items-start gap-3">
          <Info size={20} className="mt-0.5 shrink-0 text-[#827B73]" strokeWidth={1.8} aria-hidden="true" />
          <div>
            <h3 id="project-introduction-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>项目介绍</I18nText></h3>
            <p className="mt-2 max-w-3xl text-sm leading-7 text-[#645F59]">
              {PRODUCT_NAME} <I18nText>是一款面向个人藏书的开源、自托管阅读与书库管理应用。它提供读物导入、整理、检索、阅读与收听能力，适合部署在家庭 NAS 上，并通过浏览器在不同设备间访问。</I18nText></p>
          </div>
        </div>
      </section>

      <section className="mt-8 border-t border-[#DEDAD4] pt-7" aria-labelledby="project-link-title">
        <h3 id="project-link-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>项目地址</I18nText></h3>
        <a
          href={PROJECT_URL}
          target="_blank"
          rel="noreferrer"
          className="mt-4 flex min-h-14 items-center gap-3 rounded-2xl border border-[#DEDAD4] bg-white px-4 text-sm text-[#34312E] transition hover:border-[#ED4D2D] hover:text-[#ED4D2D] focus:outline-none focus:ring-4 focus:ring-[#FAD9D0]"
        >
          <Github size={20} className="shrink-0" strokeWidth={1.8} aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate font-medium">github.com/GMD170629/ermao-library</span>
          <ExternalLink size={17} className="shrink-0" strokeWidth={1.8} aria-hidden="true" />
        </a>
      </section>
    </SettingsCenterShell>
  );
}
