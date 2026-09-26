import { useI18n } from '../../../i18n/provider';
import type { SourceNodeMetadataMatch } from '../model/book-contents';
import { metadataMatchLabels } from '../model/metadata-match';

export function MetadataMatchDetails({ match }: Readonly<{ match: SourceNodeMetadataMatch | undefined }>) {
  const { t } = useI18n();
  if (!match) return null;
  const labels = metadataMatchLabels(match);
  return <div className="mt-2 text-xs leading-5 text-slate-600">
    <span className="font-medium">{t(labels.outcome)}</span>
    <span aria-hidden="true"> · </span>
    <span>{t(labels.level)}</span>
    {labels.reasons.length ? <p className="mt-0.5">{labels.reasons.map((reason) => t(reason)).join(' · ')}</p> : null}
  </div>;
}
