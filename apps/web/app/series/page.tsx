import { redirect } from 'next/navigation';

type SeriesPageProps = {
  searchParams: Promise<{ name?: string }>;
};

export default async function Page({ searchParams }: SeriesPageProps) {
  const { name } = await searchParams;
  const seriesName = name?.trim();
  if (!seriesName) redirect('/library/series');
  const params = new URLSearchParams({
    seriesName,
    sort: 'series_index',
    sortDirection: 'asc'
  });
  redirect(`/library?${params}`);
}
