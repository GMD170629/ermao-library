import { AccountPanel } from './account-panel';
import { LanguageSettings } from './language-settings';
import { SettingsCenterShell } from './settings-center-shell';
import { WorkDetailTabOrderSettings } from './work-detail-tab-order-settings';

export function GeneralSettingsPage() {
  return (
    <SettingsCenterShell title="通用" description="管理图书详情展示偏好、账户信息与当前登录状态。">
      <div className="space-y-8">
        <LanguageSettings />
        <WorkDetailTabOrderSettings />
        <AccountPanel />
      </div>
    </SettingsCenterShell>
  );
}
