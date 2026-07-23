import { AccountPanel } from './account-panel';
import { LanguageSettings } from './language-settings';
import { SettingsCenterShell } from './settings-center-shell';

export function GeneralSettingsPage() {
  return (
    <SettingsCenterShell title="个人信息" description="管理当前用户的头像、用户名、登录邮箱、密码和界面语言。">
      <div className="max-w-[920px] space-y-4">
        <AccountPanel />
        <LanguageSettings />
      </div>
    </SettingsCenterShell>
  );
}
