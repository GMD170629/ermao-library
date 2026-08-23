import { ReaderPage } from '../../../features/reader/reader-page';

type ReaderPageProps = {
  params: Promise<{ resourceId: string }>;
};

export default async function Page({ params }: ReaderPageProps) {
  const { resourceId } = await params;
  return <ReaderPage resourceId={resourceId} />;
}
