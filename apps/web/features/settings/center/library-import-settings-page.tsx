'use client';

import { FileClock, FolderCog, FolderTree } from 'lucide-react';
import { useState } from 'react';
import { ImportTasksPage } from '../../import-tasks/import-tasks-page';
import { SettingsPage } from '../settings-page';
import { cn } from '../../../components/ui/cn';
import { ImportFileManager } from './import-file-manager';
import { SettingsCenterShell } from './settings-center-shell';

export function LibraryImportSettingsPage() {
  const [activeTab, setActiveTab] = useState<'history' | 'files' | 'folders'>('history');
  const tabs = [
    { id: 'history' as const, label: '导入记录', icon: FileClock },
    { id: 'files' as const, label: '文件管理', icon: FolderTree },
    { id: 'folders' as const, label: '监控文件夹', icon: FolderCog }
  ];

  return (
    <SettingsCenterShell title="书库来源与导入" description="管理监控文件夹、识别规则与最近导入活动。">
      <div>
        <div className="mb-6 flex gap-1 overflow-x-auto border-b border-[#DEDAD4]" role="tablist" aria-label="书库来源与导入">
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
                {tab.label}
                {activeTab === tab.id ? <span className="absolute inset-x-3 bottom-0 h-0.5 bg-[#E64A2E]" /> : null}
              </button>
            );
          })}
        </div>
        <section role="tabpanel" aria-label={tabs.find((tab) => tab.id === activeTab)?.label}>
          {activeTab === 'history' ? <ImportTasksPage embedded /> : null}
          {activeTab === 'files' ? <ImportFileManager /> : null}
          {activeTab === 'folders' ? <SettingsPage embedded initialSection="监控文件夹" /> : null}
        </section>
      </div>
    </SettingsCenterShell>
  );
}
