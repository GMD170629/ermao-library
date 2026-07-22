import { BookDetailPage } from '../../../features/works/book-detail-page';

export default function Page({ params }: { params: { id: string } }) {
  return <BookDetailPage bookId={params.id} />;
}
