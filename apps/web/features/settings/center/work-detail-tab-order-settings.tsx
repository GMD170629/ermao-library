'use client';

import type { SettingsResponse } from '@/generated/api-v2';
import { apiV2Request } from '@/lib/api-v2';

import { ArrowDown, ArrowUp, GripVertical, RotateCcw, Save } from 'lucide-react';
import type { DragEvent } from 'react';
import { useEffect, useMemo, useState } from 'react';
import { Button } from '../../../components/ui/button';
import { cn } from '../../../components/ui/cn';
import { useToast } from '../../../components/ui/feedback';
import type { WorkDetailTabKey } from '../../../types/work';
import { I18nText } from '@/i18n/provider';
import {
  DEFAULT_WORK_DETAIL_TAB_ORDER,
  WORK_DETAIL_TAB_LABELS,
  moveWorkDetailTab,
  normalizeWorkDetailTabOrder,
  placeWorkDetailTab
} from '../../works/work-detail-tabs';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

const settingKey = 'workDetail.tabOrder';

export function WorkDetailTabOrderSettings() {
  const { t: i18nAttribute } = useAttributeI18n();
  const toast = useToast();
  const [order, setOrder] = useState<WorkDetailTabKey[]>([...DEFAULT_WORK_DETAIL_TAB_ORDER]);
  const [savedOrder, setSavedOrder] = useState<WorkDetailTabKey[]>([...DEFAULT_WORK_DETAIL_TAB_ORDER]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [draggedKey, setDraggedKey] = useState<WorkDetailTabKey | null>(null);
  const changed = useMemo(() => order.join('|') !== savedOrder.join('|'), [order, savedOrder]);

  useEffect(() => {
    let active = true;
    apiV2Request<SettingsResponse>('/api/v2/operations/settings')
      .then((payload) => {
        if (!active) return;
        const next = normalizeWorkDetailTabOrder(payload.values[settingKey]?.value);
        setOrder(next);
        setSavedOrder(next);
      })
      .catch((reason) => {
        if (active) toast.error('读取详情页设置失败', reason instanceof Error ? reason.message : '请稍后重试');
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [toast]);

  async function saveOrder() {
    setSaving(true);
    try {
      await apiV2Request<SettingsResponse>('/api/v2/operations/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values: { [settingKey]: { value: order } } })
      });
      setSavedOrder(order);
      window.dispatchEvent(new Event('shuku:settings-changed'));
      toast.success('详情页选项卡顺序已保存');
    } catch (reason) {
      toast.error('保存详情页设置失败', reason instanceof Error ? reason.message : '请稍后重试');
    } finally {
      setSaving(false);
    }
  }

  function startDrag(event: DragEvent<HTMLSpanElement>, key: WorkDetailTabKey) {
    setDraggedKey(key);
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', key);
  }

  return (
    <section aria-labelledby="work-detail-tabs-title" className="border-b border-[#DEDAD4] pb-8">
      <div>
        <h3 id="work-detail-tabs-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>图书详情</I18nText></h3>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-[#77716A]">
          <I18nText>调整电子书、漫画、有声书与内容结构的展示顺序。图书没有对应媒介时，该选项卡会自动隐藏。</I18nText></p>
      </div>

      <ol className="mt-5 max-w-2xl divide-y divide-[#E9E5E0] overflow-hidden rounded-2xl border border-[#DEDAD4] bg-white" aria-label={i18nAttribute("图书详情选项卡顺序")} aria-busy={loading || undefined}>
        {order.map((key, index) => (
          <li
            key={key}
            onDragOver={(event) => {
              if (draggedKey) event.preventDefault();
            }}
            onDrop={(event) => {
              event.preventDefault();
              const source = draggedKey ?? event.dataTransfer.getData('text/plain');
              if (source) setOrder((current) => placeWorkDetailTab(current, source as WorkDetailTabKey, key));
              setDraggedKey(null);
            }}
            className={cn('flex min-h-16 items-center gap-3 px-3.5 py-3 transition sm:px-4', draggedKey === key && 'bg-[#FFF5F1]')}
          >
            <span
              draggable={!loading && !saving}
              onDragStart={(event) => startDrag(event, key)}
              onDragEnd={() => setDraggedKey(null)}
              className="cursor-grab rounded-lg p-1 text-[#AAA39C] active:cursor-grabbing"
              aria-label={i18nAttribute("拖动{value0}调整顺序", { value0: WORK_DETAIL_TAB_LABELS[key] })}
            >
              <GripVertical size={18} aria-hidden="true" />
            </span>
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#F6F2EE] text-xs tabular-nums text-[#77716A]">{index + 1}</span>
            <span className="min-w-0 flex-1 text-sm font-medium text-[#2A2825]">{WORK_DETAIL_TAB_LABELS[key]}</span>
            <div className="flex gap-1">
              <button
                type="button"
                disabled={loading || index === 0}
                onClick={() => setOrder((current) => moveWorkDetailTab(current, key, -1))}
                className="flex h-9 w-9 items-center justify-center rounded-xl text-[#706A63] transition hover:bg-[#FFF0EA] hover:text-[#D94322] focus:outline-none focus:ring-4 focus:ring-[#FFE4DC] disabled:cursor-not-allowed disabled:opacity-30"
                aria-label={i18nAttribute("上移{value0}", { value0: WORK_DETAIL_TAB_LABELS[key] })}
              >
                <ArrowUp size={17} />
              </button>
              <button
                type="button"
                disabled={loading || index === order.length - 1}
                onClick={() => setOrder((current) => moveWorkDetailTab(current, key, 1))}
                className="flex h-9 w-9 items-center justify-center rounded-xl text-[#706A63] transition hover:bg-[#FFF0EA] hover:text-[#D94322] focus:outline-none focus:ring-4 focus:ring-[#FFE4DC] disabled:cursor-not-allowed disabled:opacity-30"
                aria-label={i18nAttribute("下移{value0}", { value0: WORK_DETAIL_TAB_LABELS[key] })}
              >
                <ArrowDown size={17} />
              </button>
            </div>
          </li>
        ))}
      </ol>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          type="button"
          icon={Save}
          loading={saving}
          loadingText={i18nAttribute("保存中")}
          disabled={loading || !changed}
          onClick={() => void saveOrder()}
        >
          <I18nText>保存顺序</I18nText></Button>
        <Button
          type="button"
          variant="ghost"
          icon={RotateCcw}
          disabled={loading || saving || order.join('|') === DEFAULT_WORK_DETAIL_TAB_ORDER.join('|')}
          onClick={() => setOrder([...DEFAULT_WORK_DETAIL_TAB_ORDER])}
        >
          <I18nText>恢复默认</I18nText></Button>
      </div>
    </section>
  );
}
