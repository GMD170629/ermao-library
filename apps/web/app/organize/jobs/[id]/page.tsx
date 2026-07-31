import { OrganizeJobDetailPage } from '../../../../features/organize/organize-job-detail-page';

type OrganizeJobPageProps = {
  params: Promise<{ id: string }>;
};

export default async function Page({ params }: OrganizeJobPageProps) {
  const { id } = await params;
  return <OrganizeJobDetailPage jobId={id} />;
}
