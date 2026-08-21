import { BookDetailPage } from '../../../features/books/book-detail-page';

type BookDetailPageProps = {
  params: Promise<{ bookId: string }>;
};

export default async function Page({ params }: BookDetailPageProps) {
  const { bookId } = await params;
  return <BookDetailPage bookId={bookId} />;
}
