import { BookDetailPage } from '../../../features/works/book-detail-page';

type BookDetailPageProps = {
  params: Promise<{ id: string }>;
};

export default async function Page({ params }: BookDetailPageProps) {
  const { id } = await params;
  return <BookDetailPage bookId={id} />;
}
