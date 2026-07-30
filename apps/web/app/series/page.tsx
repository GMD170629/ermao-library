import { SeriesPage } from '../../features/series/series-page';

type SeriesPageProps = {
  searchParams: Promise<{ name?: string }>;
};

export default async function Page({ searchParams }: SeriesPageProps) {
  const { name } = await searchParams;
  return <SeriesPage initialName={name ?? ''} />;
}
