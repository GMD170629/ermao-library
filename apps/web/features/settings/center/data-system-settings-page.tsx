'use client';

import { HardDrive } from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { SettingsPage } from '../settings-page';
import { SettingsCenterShell } from './settings-center-shell';
import { SettingsTabs } from './settings-tabs';
import { StorageSettingsPanel } from './storage-settings-page';
import { NetworkProxySettingsPanel } from './network-proxy-settings-panel';
import { I18nText } from '@/i18n/provider';

export function DataSystemSettingsPage() {
  const requested = useSearchParams().get('tab');
  const active = requested === 'storage' || requested === 'proxy' ? requested : 'backup';
  return (
    <SettingsCenterShell title="数据和系统" description="管理备份、存储空间和网络连接。">
      <SettingsTabs active={active} tabs={[
        { key: 'backup', label: '备份与恢复', href: '/settings/data' },
        { key: 'storage', label: '空间管理', href: '/settings/data?tab=storage' },
        { key: 'proxy', label: '网络与代理', href: '/settings/data?tab=proxy' }
      ]} />
      <div className="mt-6">
        {active === 'storage' ? <StorageSettingsPanel /> : active === 'proxy' ? <NetworkProxySettingsPanel /> : <BackupSettingsPanel />}
      </div>
    </SettingsCenterShell>
  );
}

function BackupSettingsPanel() {
  return <>
      <SettingsPage embedded initialSection="备份与恢复" />
      <section className="mt-8 border-t border-[#DEDAD4] pt-7" aria-labelledby="backup-location-title">
        <h3 id="backup-location-title" className="text-lg font-semibold text-[#2A2825]"><I18nText>存储位置</I18nText></h3>
        <div className="mt-4 flex items-start gap-3 py-2 text-sm text-[#645F59]">
          <HardDrive size={19} className="mt-0.5 text-[#827B73]" />
          <div>
            <div className="font-medium text-[#2A2825]"><I18nText>服务备份目录</I18nText></div>
            <div className="mt-1 leading-6 text-[#77716A]"><I18nText>备份保存在部署所配置的存储目录中，当前不能在应用内修改。</I18nText></div>
          </div>
        </div>
      </section>
  </>;
}
