'use client';

import Image from 'next/image';
import { useState } from 'react';
import { withBasePath } from '../../../lib/base-path';

type AccountAvatarSource = {
  avatarImageUrl?: string | null;
  avatarUrl?: string | null;
};

type AccountAvatarProps = {
  account: AccountAvatarSource | null | undefined;
  alt: string;
  size: number;
  className?: string;
  priority?: boolean;
};

/** The server owns both uploaded and default images; this view never invents one. */
export function AccountAvatar({ account, ...props }: AccountAvatarProps) {
  const source = account?.avatarImageUrl ?? account?.avatarUrl ?? null;
  // A changed account image starts a new native image-loading/error lifecycle.
  return <ResponseAvatar key={source} source={source} {...props} />;
}

function ResponseAvatar({
  source,
  alt,
  size,
  className,
  priority
}: Omit<AccountAvatarProps, 'account'> & { source: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!source || failed) {
    return <span aria-label={alt} role="img" className={className} style={{ width: size, height: size }} />;
  }
  return (
    <Image
      src={withBasePath(source)}
      alt={alt}
      width={size}
      height={size}
      className={className}
      priority={priority}
      unoptimized
      onError={() => setFailed(true)}
    />
  );
}
