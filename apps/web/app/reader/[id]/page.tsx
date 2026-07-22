import { ReaderPage } from '../../../features/reader/reader-page';

export default function Page({ params }: { params: { id: string } }) {
  return <ReaderPage editionId={params.id} />;
}
