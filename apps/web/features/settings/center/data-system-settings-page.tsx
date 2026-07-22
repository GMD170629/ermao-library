import { HardDrive } from 'lucide-react';
import { SettingsPage } from '../settings-page';
import { SettingsCenterShell } from './settings-center-shell';

export function DataSystemSettingsPage() {
  return (
    <SettingsCenterShell title="数据与系统" description="备份书库数据，并在需要时恢复。">
      <SettingsPage embedded initialSection="备份与恢复" />
      <section className="mt-8 border-t border-[#DEDAD4] pt-7" aria-labelledby="backup-location-title">
        <h3 id="backup-location-title" className="text-lg font-semibold text-[#2A2825]">存储位置</h3>
        <div className="mt-4 flex items-start gap-3 py-2 text-sm text-[#645F59]">
          <HardDrive size={19} className="mt-0.5 text-[#827B73]" />
          <div>
            <div className="font-medium text-[#2A2825]">服务备份目录</div>
            <div className="mt-1 leading-6 text-[#77716A]">备份保存在部署所配置的存储目录中，当前不能在应用内修改。</div>
          </div>
        </div>
      </section>
    </SettingsCenterShell>
  );
}
