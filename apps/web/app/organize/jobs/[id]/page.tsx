import { OrganizeJobDetailPage } from '../../../../features/organize/organize-job-detail-page';

export default function Page({ params }: { params: { id: string } }) {
  return <OrganizeJobDetailPage jobId={params.id} />;
}
