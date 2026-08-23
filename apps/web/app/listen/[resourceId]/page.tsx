import { AudioListenRedirect } from '../../../features/audio/audio-listen-redirect';

type ListenPageProps = {
  params: Promise<{ resourceId: string }>;
};

export default async function ListenPage({ params }: ListenPageProps) {
  const { resourceId } = await params;
  return <AudioListenRedirect resourceId={resourceId} />;
}
