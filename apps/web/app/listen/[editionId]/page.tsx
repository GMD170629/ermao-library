import { AudioListenRedirect } from '../../../features/audio/audio-listen-redirect';

type ListenPageProps = {
  params: Promise<{ editionId: string }>;
};

export default async function ListenPage({ params }: ListenPageProps) {
  const { editionId } = await params;
  return <AudioListenRedirect editionId={editionId} />;
}
