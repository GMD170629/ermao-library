'use client';

import { useSearchParams } from 'next/navigation';
import { MetadataProvidersPanel } from '../../organize/metadata-providers-panel';
import { ClassificationManagementPanel } from '../../organize/classification-management-panel';
import { DuplicateManagementPanel } from '../../organize/duplicate-management-panel';
import { OrganizePage } from '../../organize/organize-page';
import { RecognitionSettingsPanel } from '../../organize/recognition-settings-panel';
import { SettingsCenterShell } from './settings-center-shell';
import { SettingsTabs } from './settings-tabs';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

export function OrganizeSettingsPage() {
  const { t: i18nAttribute } = useAttributeI18n();
  const searchParams = useSearchParams();
  const requested = searchParams.get('tab');
  const active = requested === 'recognition' || requested === 'metadata'
    ? 'recognition'
    : requested === 'duplicates'
      ? 'duplicates'
      : requested === 'categories'
        ? 'categories'
    : requested === 'providers'
      ? 'providers'
      : 'queue';

  return (
    <SettingsCenterShell title={i18nAttribute("智能整理")} description={i18nAttribute("由整理策略主动扫描书库，并通过可扩展的数据源插件识别和补全元数据。")}>
      <SettingsTabs
        active={active}
        tabs={[
          { key: 'queue', label: '整理队列', href: '/settings/organize?tab=queue' },
          { key: 'duplicates', label: '重复项', href: '/settings/organize?tab=duplicates' },
          { key: 'categories', label: '分类治理', href: '/settings/organize?tab=categories' },
          { key: 'recognition', label: '识别设置', href: '/settings/organize?tab=recognition' },
          { key: 'providers', label: '数据源配置', href: '/settings/organize?tab=providers' }
        ]}
      />
      <div className="mt-6">
        {active === 'duplicates'
          ? <DuplicateManagementPanel />
          : active === 'categories'
            ? <ClassificationManagementPanel />
            : active === 'recognition'
          ? <RecognitionSettingsPanel />
          : active === 'providers'
            ? <MetadataProvidersPanel />
            : <OrganizePage embedded jobBasePath="/settings/organize/jobs" />}
      </div>
    </SettingsCenterShell>
  );
}
