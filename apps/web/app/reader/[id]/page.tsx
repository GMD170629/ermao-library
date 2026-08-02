import { ReaderPage } from '../../../features/reader/reader-page';

type ReaderPageProps = {
  params: Promise<{ id: string }>;
};

export default async function Page({ params }: ReaderPageProps) {
  const { id } = await params;
  return <ReaderPage volumeId={id} />;
}
