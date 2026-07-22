import { AudioListenRedirect } from '../../../features/audio/audio-listen-redirect';

export default function ListenPage({ params }: { params: { editionId: string } }) {
  return <AudioListenRedirect editionId={params.editionId} />;
}
