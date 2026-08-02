import { AudioListenRedirect } from '../../../features/audio/audio-listen-redirect';

type ListenPageProps = {
  params: Promise<{ volumeId: string }>;
};

export default async function ListenPage({ params }: ListenPageProps) {
  const { volumeId } = await params;
  return <AudioListenRedirect volumeId={volumeId} />;
}
