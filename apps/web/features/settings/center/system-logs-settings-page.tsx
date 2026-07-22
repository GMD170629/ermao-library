import { ManagementLogsPage } from '../../management/management-logs-page';
import { SettingsCenterShell } from './settings-center-shell';

export function SystemLogsSettingsPage() {
  return (
    <SettingsCenterShell title="系统日志" description="查看导入、整理、下载与系统操作产生的真实记录。">
      <ManagementLogsPage embedded />
    </SettingsCenterShell>
  );
}
