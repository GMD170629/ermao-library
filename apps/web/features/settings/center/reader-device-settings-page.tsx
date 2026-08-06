'use client';

import {
  DEFAULT_READER_PREFERENCES,
  normalizeReaderPreferences,
  type ReaderPreferences
} from '@shuku/reader-core';
import { BookOpen, Check, FileText, Headphones, Images, Minus, MonitorSmartphone, MousePointer2, Palette, Plus, RotateCcw, Sparkles } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { Button } from '../../../components/ui/button';
import { useToast } from '../../../components/ui/feedback';
import { useAppSession } from '../../../components/layout/app-session-context';
import {
  READER_COMIC_DIRECTION_OPTIONS,
  READER_COMIC_IMAGE_FIT_OPTIONS,
  READER_COMIC_IMAGE_VARIANT_OPTIONS,
  READER_COMIC_FLOW_OPTIONS,
  READER_FLOW_OPTIONS,
  READER_FONT_FAMILY_OPTIONS,
  READER_FONT_SIZE_OPTIONS,
  READER_LINE_HEIGHT_OPTIONS,
  READER_FONT_WEIGHT_OPTIONS,
  READER_LETTER_SPACING_OPTIONS,
  READER_PAGE_MARGIN_OPTIONS,
  READER_PROGRESS_STYLE_OPTIONS,
  READER_PAGE_GAP_OPTIONS,
  READER_PAGE_TURN_ANIMATION_OPTIONS,
  READER_PDF_FIT_OPTIONS,
  READER_PDF_FLOW_OPTIONS,
  READER_PDF_ROTATION_OPTIONS,
  READER_PDF_CROP_OPTIONS,
  READER_SPREAD_MODE_OPTIONS,
  READER_TAP_ZONE_OPTIONS,
  READER_THEME_OPTIONS,
  closestReaderOptionValue
} from '../../reader/reader-preference-options';
import { READER_PAGE_WIDTH_MAXIMUM, READER_PAGE_WIDTH_MINIMUM } from '../../reader/v3/page-width';
import { readerThemeSurfaces } from '../../reader/reader-theme';
import {
  AUDIO_PLAYBACK_RATE_OPTIONS,
  clearAudioDevicePreferences,
  readAudioDevicePreferences,
  writeAudioDevicePreferences
} from '../../../lib/audio-device-preferences';
import {
  clearDeviceReaderPreferences,
  readDeviceReaderPreferences,
  writeDeviceReaderPreferences
} from '../../../lib/reader-device-preferences';
import { useI18n } from '../../../i18n/provider';
import { SettingsCenterShell } from './settings-center-shell';

type Choice = { value: string; label: string };

function SettingsSection({
  icon,
  title,
  description,
  children,
  horizontal = false
}: {
  icon: ReactNode;
  title: string;
  description: string;
  children: ReactNode;
  horizontal?: boolean;
}) {
  return (
    <section className={`rounded-[22px] border border-[#E5E0D8] bg-[#FFFEFC] p-3 sm:p-4 ${
      horizontal ? 'sm:grid sm:grid-cols-[minmax(14rem,0.8fr)_minmax(22rem,1.2fr)] sm:items-center sm:gap-4' : ''
    }`}>
      <div className="flex items-center gap-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#FCE5DE] text-[#D94A2E]">{icon}</span>
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-[#2A2825]">{title}</h3>
          <p className="mt-0.5 text-xs leading-5 text-[#77716A]">{description}</p>
        </div>
      </div>
      <div className={`space-y-2 ${horizontal ? 'mt-3 sm:mt-0' : 'mt-3.5'}`}>{children}</div>
    </section>
  );
}

function SettingRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-2 sm:grid-cols-[4.5rem_minmax(0,1fr)] sm:gap-2.5">
      <div className="text-sm font-medium text-[#77716A]">{label}</div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function ChoiceField({
  label,
  value,
  options,
  columns,
  disabled = false,
  onChange
}: {
  label: string;
  value: string;
  options: ReadonlyArray<Choice>;
  columns?: number;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const { t } = useI18n();
  const columnCount = columns ?? Math.min(options.length, 5);
  const denseLabels = options.length >= 5;
  const widthClass = options.length <= 2
    ? 'max-w-[18rem]'
    : options.length === 3
      ? 'max-w-[20rem]'
      : options.length === 4
        ? 'max-w-[23rem]'
        : 'max-w-[26rem]';
  return (
    <SettingRow label={label}>
      <div
        role="group"
        aria-label={label}
        aria-disabled={disabled}
        className={`grid w-full gap-1 rounded-xl bg-[#F2EEE8] p-1 ${widthClass} ${disabled ? 'opacity-45' : ''}`}
        style={{ gridTemplateColumns: `repeat(${columnCount}, minmax(0, 1fr))` }}
      >
        {options.map((option) => {
          const selected = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={selected}
              disabled={disabled}
              onClick={() => onChange(option.value)}
              className={`min-h-10 min-w-0 rounded-[10px] font-semibold transition focus:outline-none focus:ring-2 focus:ring-[#EF8B73]/60 active:scale-[0.98] sm:px-1.5 sm:text-xs ${
                denseLabels ? 'px-0 text-[10px]' : 'px-0.5 text-[11px]'
              } ${
                selected
                  ? 'bg-white text-[#B84329] shadow-[0_2px_7px_rgba(68,52,42,0.12)]'
                  : 'text-[#756F68] hover:bg-white/65 hover:text-[#37332F]'
              }`}
            >
              <span className="block truncate">{t(option.label)}</span>
            </button>
          );
        })}
      </div>
    </SettingRow>
  );
}

function ThemeField({
  label,
  value,
  onChange
}: {
  label: string;
  value: ReaderPreferences['appearance']['theme'];
  onChange: (value: ReaderPreferences['appearance']['theme']) => void;
}) {
  const { t } = useI18n();
  return (
    <SettingRow label={label}>
      <div className="grid w-full max-w-[26rem] grid-cols-5 gap-1 rounded-xl bg-[#F2EEE8] p-1" role="group" aria-label={label}>
        {READER_THEME_OPTIONS.map((option) => {
          const selected = value === option.value;
          const surface = readerThemeSurfaces[option.value];
          return (
            <button
              key={option.value}
              type="button"
              aria-label={t(option.label)}
              aria-pressed={selected}
              onClick={() => onChange(option.value)}
              className={`flex min-h-12 items-center justify-center rounded-[10px] transition focus:outline-none focus:ring-2 focus:ring-[#EF8B73]/60 active:scale-[0.98] ${
                selected ? 'bg-white shadow-[0_2px_7px_rgba(68,52,42,0.12)]' : 'hover:bg-white/55'
              }`}
            >
              <span
                className={`flex h-7 w-7 items-center justify-center rounded-full border shadow-sm ${
                  selected ? 'border-[#C96B52]' : 'border-black/10'
                }`}
                style={{ backgroundColor: surface.background, color: surface.color }}
              >
                {selected ? <Check size={14} strokeWidth={2.5} /> : null}
              </span>
            </button>
          );
        })}
      </div>
    </SettingRow>
  );
}

function StepperField({
  label,
  value,
  minimum,
  maximum,
  step,
  onChange
}: {
  label: string;
  value: number;
  minimum: number;
  maximum: number;
  step: number;
  onChange: (value: number) => void;
}) {
  const { t } = useI18n();
  const normalizedValue = Math.round(value * 100);
  return (
    <SettingRow label={label}>
      <div className="flex min-h-12 w-full max-w-[18rem] items-center rounded-xl bg-[#F2EEE8] p-1">
        <button
          type="button"
          aria-label={t('{value0}减少', { value0: label })}
          disabled={value <= minimum}
          onClick={() => onChange(Math.max(minimum, Number((value - step).toFixed(1))))}
          className="flex h-10 w-12 items-center justify-center rounded-[10px] text-[#37332F] transition hover:bg-white/65 focus:outline-none focus:ring-2 focus:ring-[#EF8B73]/60 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-35"
        >
          <Minus size={16} />
        </button>
        <span className="min-w-0 flex-1 text-center text-sm font-medium tabular-nums text-[#2D2925]">{normalizedValue}%</span>
        <button
          type="button"
          aria-label={t('{value0}增加', { value0: label })}
          disabled={value >= maximum}
          onClick={() => onChange(Math.min(maximum, Number((value + step).toFixed(1))))}
          className="flex h-10 w-12 items-center justify-center rounded-[10px] text-[#37332F] transition hover:bg-white/65 focus:outline-none focus:ring-2 focus:ring-[#EF8B73]/60 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-35"
        >
          <Plus size={16} />
        </button>
      </div>
    </SettingRow>
  );
}

function RangeField({
  label,
  value,
  minimum,
  maximum,
  step,
  suffix,
  onChange
}: {
  label: string;
  value: number;
  minimum: number;
  maximum: number;
  step: number;
  suffix?: string;
  onChange: (value: number) => void;
}) {
  return (
    <SettingRow label={label}>
      <label className="flex min-h-12 w-full max-w-[23rem] items-center gap-3 rounded-xl bg-[#F2EEE8] px-3">
        <input
          type="range"
          min={minimum}
          max={maximum}
          step={step}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
          className="h-8 min-w-0 flex-1 cursor-pointer accent-[#E85A3A]"
        />
        <span className="w-11 shrink-0 text-right text-xs tabular-nums text-[#77716A]">{value}{suffix}</span>
      </label>
    </SettingRow>
  );
}

export function ReaderDeviceSettingsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const userId = useAppSession()?.user?.id ?? '';
  const [preferences, setPreferences] = useState<ReaderPreferences>(() => normalizeReaderPreferences(DEFAULT_READER_PREFERENCES));
  const [audio, setAudio] = useState({ playbackRate: 1, volume: 1 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!userId) {
      setPreferences(normalizeReaderPreferences(DEFAULT_READER_PREFERENCES));
      setAudio({ playbackRate: 1, volume: 1 });
      setLoading(false);
      return;
    }
    setPreferences(readDeviceReaderPreferences(userId, DEFAULT_READER_PREFERENCES));
    const storedAudio = readAudioDevicePreferences(userId);
    setAudio({
      playbackRate: Number(storedAudio.playbackRate ?? 1),
      volume: Number(storedAudio.volume ?? 1)
    });
    setLoading(false);
  }, [userId]);

  function updatePreferences(nextPreferences: ReaderPreferences) {
    setPreferences(nextPreferences);
    if (userId) writeDeviceReaderPreferences(userId, nextPreferences);
  }

  function updateAudio(nextAudio: typeof audio) {
    setAudio(nextAudio);
    if (userId) writeAudioDevicePreferences(nextAudio, userId);
  }

  function reset() {
    if (!userId) return;
    clearDeviceReaderPreferences(userId);
    clearAudioDevicePreferences(userId);
    setPreferences(normalizeReaderPreferences(DEFAULT_READER_PREFERENCES));
    setAudio({ playbackRate: 1, volume: 1 });
    toast.success(t('当前设备的阅读器偏好已恢复默认'));
  }

  return (
    <SettingsCenterShell
      title={t('当前设备偏好')}
      description={t('这些设置仅保存在当前用户的当前设备，并统一应用到这台设备上的所有图书，不会改变其他设备或其他用户的阅读器。')}
      actions={(
        <Button variant="secondary" icon={RotateCcw} disabled={loading || !userId} onClick={reset}>{t('恢复默认')}</Button>
      )}
    >
      <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-[#E7DDD5] bg-[#FFF8F3] px-3.5 py-2.5 text-xs leading-5 text-[#755A4B]">
        <MonitorSmartphone size={19} className="mt-0.5 shrink-0" />
        <span>{t('偏好使用“用户 + 设备”命名空间保存。清除浏览器网站数据会同时清除这些设置。')}</span>
      </div>

      <div className="-mx-3 max-w-[1040px] space-y-3 sm:mx-0">
        <SettingsSection
          icon={<Palette size={19} />}
          title={t('阅读外观')}
          description={t('主题会同时应用到 EPUB、漫画和 PDF 阅读器。')}
          horizontal
        >
          <ThemeField
            label={t('主题')}
            value={preferences.appearance.theme}
            onChange={(theme) => updatePreferences({ ...preferences, appearance: { ...preferences.appearance, theme, themeMode: 'manual' } })}
          />
          <ChoiceField label={t('跟随系统明暗')} value={preferences.appearance.themeMode} options={[{ value: 'manual', label: '关闭' }, { value: 'system', label: '开启' }]} onChange={(themeMode) => updatePreferences({ ...preferences, appearance: { ...preferences.appearance, themeMode: themeMode as ReaderPreferences['appearance']['themeMode'] } })} />
        </SettingsSection>

        <div className="grid items-start gap-3 xl:grid-cols-2">
          <SettingsSection
            icon={<BookOpen size={19} />}
            title={t('电子书阅读器')}
            description={t('设置当前设备打开 EPUB 时使用的默认排版方式。')}
          >
            <ChoiceField
              label={t('字号')}
              value={closestReaderOptionValue(preferences.epub.fontSize, READER_FONT_SIZE_OPTIONS)}
              options={READER_FONT_SIZE_OPTIONS}
              onChange={(fontSize) => updatePreferences({ ...preferences, epub: { ...preferences.epub, fontSize: Number(fontSize) } })}
            />
            <RangeField label={t('精细字号')} value={preferences.epub.fontSize} minimum={14} maximum={30} step={1} suffix="px" onChange={(fontSize) => updatePreferences({ ...preferences, epub: { ...preferences.epub, fontSize } })} />
            <ChoiceField
              label={t('行距')}
              value={closestReaderOptionValue(preferences.epub.lineHeight, READER_LINE_HEIGHT_OPTIONS)}
              options={READER_LINE_HEIGHT_OPTIONS}
              onChange={(lineHeight) => updatePreferences({ ...preferences, epub: { ...preferences.epub, lineHeight: Number(lineHeight) } })}
            />
            <ChoiceField
              label={t('字体')}
              value={preferences.epub.fontFamily}
              options={READER_FONT_FAMILY_OPTIONS}
              onChange={(fontFamily) => updatePreferences({ ...preferences, epub: { ...preferences.epub, fontFamily: fontFamily as ReaderPreferences['epub']['fontFamily'] } })}
            />
            <ChoiceField label={t('字重')} value={String(preferences.epub.fontWeight)} options={READER_FONT_WEIGHT_OPTIONS} onChange={(fontWeight) => updatePreferences({ ...preferences, epub: { ...preferences.epub, fontWeight: Number(fontWeight) as ReaderPreferences['epub']['fontWeight'] } })} />
            <ChoiceField label={t('字间距')} value={String(preferences.epub.letterSpacing)} options={READER_LETTER_SPACING_OPTIONS} onChange={(letterSpacing) => updatePreferences({ ...preferences, epub: { ...preferences.epub, letterSpacing: Number(letterSpacing) as ReaderPreferences['epub']['letterSpacing'] } })} />
            <ChoiceField label={t('页边距')} value={preferences.epub.pageMargin} options={READER_PAGE_MARGIN_OPTIONS} onChange={(pageMargin) => updatePreferences({ ...preferences, epub: { ...preferences.epub, pageMargin: pageMargin as ReaderPreferences['epub']['pageMargin'] } })} />
            <RangeField label={t('页宽')} value={preferences.epub.pageWidth} minimum={READER_PAGE_WIDTH_MINIMUM} maximum={READER_PAGE_WIDTH_MAXIMUM} step={10} suffix="px" onChange={(pageWidth) => updatePreferences({ ...preferences, epub: { ...preferences.epub, pageWidth } })} />
            <ChoiceField
              label={t('排版')}
              value={preferences.epub.flow}
              options={READER_FLOW_OPTIONS}
              onChange={(flow) => updatePreferences({ ...preferences, epub: { ...preferences.epub, flow: flow as ReaderPreferences['epub']['flow'] } })}
            />
            <ChoiceField label={t('页面')} value={preferences.epub.spreadMode} options={READER_SPREAD_MODE_OPTIONS} onChange={(spreadMode) => updatePreferences({ ...preferences, epub: { ...preferences.epub, spreadMode: spreadMode as ReaderPreferences['epub']['spreadMode'] } })} />
            <ChoiceField
              label={t('安全优化')}
              value={String(preferences.epub.optimization.enabled)}
              options={[{ value: 'true', label: '开启' }, { value: 'false', label: '关闭' }]}
              onChange={(enabled) => updatePreferences({ ...preferences, epub: { ...preferences.epub, optimization: { ...preferences.epub.optimization, enabled: enabled === 'true' } } })}
            />
          </SettingsSection>

          <SettingsSection
            icon={<Images size={19} />}
            title={t('漫画阅读器')}
            description={t('设置当前设备的漫画模式、翻页、显示和缩放方式。')}
          >
            <ChoiceField label={t('阅读方式')} value={preferences.comic.flow} options={READER_COMIC_FLOW_OPTIONS} onChange={(flow) => updatePreferences({ ...preferences, comic: { ...preferences.comic, flow: flow as ReaderPreferences['comic']['flow'] } })} />
            <ChoiceField label={t('模式')} value={preferences.comic.mode} options={READER_SPREAD_MODE_OPTIONS.filter((option) => option.value !== 'auto')} disabled={preferences.comic.flow === 'vertical'} onChange={(mode) => updatePreferences({ ...preferences, comic: { ...preferences.comic, mode: mode as ReaderPreferences['comic']['mode'] } })} />
            <ChoiceField label={t('双页时封面单独显示')} value={String(preferences.comic.coverSingle)} options={[{ value: 'true', label: '开启' }, { value: 'false', label: '关闭' }]} disabled={preferences.comic.flow === 'vertical' || preferences.comic.mode !== 'double'} onChange={(coverSingle) => updatePreferences({ ...preferences, comic: { ...preferences.comic, coverSingle: coverSingle === 'true' } })} />
            <ChoiceField label={t('页间距')} value={String(preferences.comic.pageGap)} options={READER_PAGE_GAP_OPTIONS} disabled={preferences.comic.flow === 'vertical'} onChange={(pageGap) => updatePreferences({ ...preferences, comic: { ...preferences.comic, pageGap: Number(pageGap) as ReaderPreferences['comic']['pageGap'] } })} />
            <RangeField label={t('页宽')} value={preferences.comic.pageWidth} minimum={READER_PAGE_WIDTH_MINIMUM} maximum={READER_PAGE_WIDTH_MAXIMUM} step={10} suffix="px" onChange={(pageWidth) => updatePreferences({ ...preferences, comic: { ...preferences.comic, pageWidth } })} />
            <ChoiceField label={t('翻页')} value={preferences.comic.pageTurnAnimation} options={READER_PAGE_TURN_ANIMATION_OPTIONS} onChange={(pageTurnAnimation) => updatePreferences({ ...preferences, comic: { ...preferences.comic, pageTurnAnimation: pageTurnAnimation as ReaderPreferences['comic']['pageTurnAnimation'] } })} />
            <ChoiceField label={t('适配')} value={preferences.comic.imageFit} options={READER_COMIC_IMAGE_FIT_OPTIONS} onChange={(imageFit) => updatePreferences({ ...preferences, comic: { ...preferences.comic, imageFit: imageFit as ReaderPreferences['comic']['imageFit'] } })} />
            <ChoiceField label={t('画质')} value={preferences.comic.imageVariant} options={READER_COMIC_IMAGE_VARIANT_OPTIONS} onChange={(imageVariant) => updatePreferences({ ...preferences, comic: { ...preferences.comic, imageVariant: imageVariant as ReaderPreferences['comic']['imageVariant'] } })} />
            <ChoiceField label={t('方向')} value={preferences.comic.direction} options={READER_COMIC_DIRECTION_OPTIONS} disabled={preferences.comic.flow === 'vertical'} onChange={(direction) => updatePreferences({ ...preferences, comic: { ...preferences.comic, direction: direction as ReaderPreferences['comic']['direction'] } })} />
            <StepperField label={t('缩放')} value={preferences.comic.zoom} minimum={0.6} maximum={2.4} step={0.1} onChange={(zoom) => updatePreferences({ ...preferences, comic: { ...preferences.comic, zoom } })} />
          </SettingsSection>
        </div>

        <div className="grid items-start gap-3 xl:grid-cols-2">
          <SettingsSection
            icon={<MousePointer2 size={19} />}
            title={t('阅读操作')}
            description={t('设置所有阅读格式共用的点击、滑动和按键行为。')}
          >
            <ChoiceField label={t('点击区域')} value={preferences.interaction.tapZones} options={READER_TAP_ZONE_OPTIONS} onChange={(tapZones) => updatePreferences({ ...preferences, interaction: { ...preferences.interaction, tapZones: tapZones as ReaderPreferences['interaction']['tapZones'] } })} />
            <ChoiceField label={t('滑动翻页')} value={String(preferences.interaction.swipePageTurn)} options={[{ value: 'true', label: '开启' }, { value: 'false', label: '关闭' }]} onChange={(enabled) => updatePreferences({ ...preferences, interaction: { ...preferences.interaction, swipePageTurn: enabled === 'true' } })} />
            <ChoiceField label={t('键盘翻页')} value={String(preferences.interaction.keyboardPageTurn)} options={[{ value: 'true', label: '开启' }, { value: 'false', label: '关闭' }]} onChange={(enabled) => updatePreferences({ ...preferences, interaction: { ...preferences.interaction, keyboardPageTurn: enabled === 'true' } })} />
            <ChoiceField label={t('音量键翻页')} value={String(preferences.interaction.volumeKeyPageTurn)} options={[{ value: 'true', label: '开启' }, { value: 'false', label: '关闭' }]} onChange={(enabled) => updatePreferences({ ...preferences, interaction: { ...preferences.interaction, volumeKeyPageTurn: enabled === 'true' } })} />
            <ChoiceField label={t('进度显示')} value={preferences.display.progressStyle} options={READER_PROGRESS_STYLE_OPTIONS} onChange={(progressStyle) => updatePreferences({ ...preferences, display: { ...preferences.display, progressStyle: progressStyle as ReaderPreferences['display']['progressStyle'] } })} />
            <ChoiceField label={t('常显时钟')} value={String(preferences.display.showClock)} options={[{ value: 'true', label: '开启' }, { value: 'false', label: '关闭' }]} onChange={(showClock) => updatePreferences({ ...preferences, display: { ...preferences.display, showClock: showClock === 'true' } })} />
            <ChoiceField label={t('保持屏幕唤醒')} value={String(preferences.interaction.keepScreenAwake)} options={[{ value: 'true', label: '开启' }, { value: 'false', label: '关闭' }]} onChange={(keepScreenAwake) => updatePreferences({ ...preferences, interaction: { ...preferences.interaction, keepScreenAwake: keepScreenAwake === 'true' } })} />
          </SettingsSection>

          <SettingsSection
            icon={<Sparkles size={19} />}
            title={t('智能排版')}
            description={t('安全处理普通正文缩进，同时保留标题、诗歌、列表和复杂排版。')}
          >
            <ChoiceField label={t('重复缩进去重')} value={String(preferences.epub.optimization.deduplicateIndent)} options={[{ value: 'true', label: '开启' }, { value: 'false', label: '关闭' }]} onChange={(enabled) => updatePreferences({ ...preferences, epub: { ...preferences.epub, optimization: { ...preferences.epub.optimization, deduplicateIndent: enabled === 'true' } } })} />
            <ChoiceField label={t('无缩进正文补齐')} value={String(preferences.epub.optimization.indentUnindented)} options={[{ value: 'true', label: '开启' }, { value: 'false', label: '关闭' }]} onChange={(enabled) => updatePreferences({ ...preferences, epub: { ...preferences.epub, optimization: { ...preferences.epub.optimization, indentUnindented: enabled === 'true' } } })} />
          </SettingsSection>
        </div>

        <div className="grid items-start gap-3 xl:grid-cols-2">
          <SettingsSection
            icon={<FileText size={19} />}
            title={t('PDF 阅读器')}
            description={t('设置当前设备打开 PDF 时的默认缩放和适配方式。')}
          >
            <StepperField label={t('缩放')} value={preferences.pdf.zoom} minimum={0.6} maximum={2.4} step={0.1} onChange={(zoom) => updatePreferences({ ...preferences, pdf: { ...preferences.pdf, zoom } })} />
            <RangeField label={t('页宽')} value={preferences.pdf.pageWidth} minimum={READER_PAGE_WIDTH_MINIMUM} maximum={READER_PAGE_WIDTH_MAXIMUM} step={10} suffix="px" onChange={(pageWidth) => updatePreferences({ ...preferences, pdf: { ...preferences.pdf, pageWidth } })} />
            <ChoiceField label={t('适配')} value={preferences.pdf.fit} options={READER_PDF_FIT_OPTIONS} onChange={(fit) => updatePreferences({ ...preferences, pdf: { ...preferences.pdf, fit: fit as ReaderPreferences['pdf']['fit'] } })} />
            <ChoiceField label={t('阅读方式')} value={preferences.pdf.flow} options={READER_PDF_FLOW_OPTIONS} onChange={(flow) => updatePreferences({ ...preferences, pdf: { ...preferences.pdf, flow: flow as ReaderPreferences['pdf']['flow'] } })} />
            <ChoiceField label={t('页面旋转')} value={String(preferences.pdf.rotation)} options={READER_PDF_ROTATION_OPTIONS} onChange={(rotation) => updatePreferences({ ...preferences, pdf: { ...preferences.pdf, rotation: Number(rotation) as ReaderPreferences['pdf']['rotation'] } })} />
            <ChoiceField label={t('自动裁白边')} value={preferences.pdf.cropMargins} options={READER_PDF_CROP_OPTIONS} onChange={(cropMargins) => updatePreferences({ ...preferences, pdf: { ...preferences.pdf, cropMargins: cropMargins as ReaderPreferences['pdf']['cropMargins'] } })} />
          </SettingsSection>

          <SettingsSection
            icon={<Headphones size={19} />}
            title={t('音频播放器')}
            description={t('设置当前用户在这台设备上的默认播放速度和音量。')}
          >
            <ChoiceField
              label={t('播放速度')}
              value={String(audio.playbackRate)}
              columns={4}
              options={AUDIO_PLAYBACK_RATE_OPTIONS.map((playbackRate) => ({ value: String(playbackRate), label: `${playbackRate}×` }))}
              onChange={(playbackRate) => updateAudio({ ...audio, playbackRate: Number(playbackRate) })}
            />
            <RangeField label={t('音量')} value={Math.round(audio.volume * 100)} minimum={0} maximum={100} step={5} suffix="%" onChange={(volume) => updateAudio({ ...audio, volume: volume / 100 })} />
          </SettingsSection>
        </div>
      </div>
    </SettingsCenterShell>
  );
}
