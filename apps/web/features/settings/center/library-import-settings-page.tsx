'use client';

import { FileClock, FolderCog, FolderTree, SlidersHorizontal } from 'lucide-react';
import { useState } from 'react';
import { ImportTasksPage } from '../../import-tasks/import-tasks-page';
import { SettingsPage } from '../settings-page';
import { cn } from '../../../components/ui/cn';
import { ImportFileManager } from './import-file-manager';
import { SettingsCenterShell } from './settings-center-shell';
import { ImportPreferencesPanel } from './import-preferences-panel';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

export function LibraryImportSettingsPage() {
  const { t: i18nAttribute } = useAttributeI18n();
  const [activeTab, setActiveTab] = useState<'history' | 'files' | 'folders' | 'preferences'>('history');
  const tabs = [
    { id: 'history' as const, label: '导入记录', icon: FileClock },
    { id: 'files' as const, label: '文件管理', icon: FolderTree },
    { id: 'folders' as const, label: '监控文件夹', icon: FolderCog },
    { id: 'preferences' as const, label: '偏好设置', icon: SlidersHorizontal }
  ];

  return (
    <SettingsCenterShell title={i18nAttribute("书库来源和导入")} description={i18nAttribute("管理监控文件夹、识别规则与最近导入活动。")}>
      <div>
        <div className="mb-6 flex gap-1 overflow-x-auto border-b border-[#DEDAD4]" role="tablist" aria-label={i18nAttribute("书库来源与导入")}>
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  'relative flex min-h-12 shrink-0 items-center gap-2 px-4 text-sm font-medium outline-none transition-colors focus-visible:bg-[#FAF2EE]',
                  activeTab === tab.id ? 'text-[#D94724]' : 'text-[#77716A] hover:text-[#2A2825]'
                )}
              >
                <Icon size={17} />
                {i18nAttribute(tab.label)}
                {activeTab === tab.id ? <span className="absolute inset-x-3 bottom-0 h-0.5 bg-[#E64A2E]" /> : null}
              </button>
            );
          })}
        </div>
        <section role="tabpanel" aria-label={tabs.find((tab) => tab.id === activeTab)?.label}>
          {activeTab === 'history' ? <ImportTasksPage embedded /> : null}
          {activeTab === 'files' ? <ImportFileManager /> : null}
          {activeTab === 'folders' ? <SettingsPage embedded initialSection={i18nAttribute("监控文件夹")} /> : null}
          {activeTab === 'preferences' ? <ImportPreferencesPanel /> : null}
        </section>
      </div>
    </SettingsCenterShell>
  );
}
