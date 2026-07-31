import { OrganizeJobDetailPage } from '../../../../../features/organize/organize-job-detail-page';
import { SettingsCenterShell } from '../../../../../features/settings/center/settings-center-shell';

type OrganizeJobSettingsPageProps = {
  params: Promise<{ id: string }>;
};

export default async function Page({ params }: OrganizeJobSettingsPageProps) {
  const { id } = await params;
  return (
    <SettingsCenterShell title="整理详情" description="查看本次整理的状态、候选字段与数据来源。">
      <OrganizeJobDetailPage jobId={id} embedded />
    </SettingsCenterShell>
  );
}
