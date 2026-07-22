import { OrganizeJobDetailPage } from '../../../../../features/organize/organize-job-detail-page';
import { SettingsCenterShell } from '../../../../../features/settings/center/settings-center-shell';

export default function Page({ params }: { params: { id: string } }) {
  return (
    <SettingsCenterShell title="整理详情" description="查看本次整理的状态、候选字段与数据来源。">
      <OrganizeJobDetailPage jobId={params.id} embedded />
    </SettingsCenterShell>
  );
}
