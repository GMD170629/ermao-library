'use client';

import Image from 'next/image';
import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { withBasePath } from '../../lib/base-path';
import { cn } from '../ui/cn';

export type CoverBook = {
  id?: string | number;
  title: string;
  author: string;
  format: string;
  gradient: string;
  coverUrl?: string;
  coverStatus?: string;
};

export function Cover({
  book,
  className = '',
  small = false,
  size,
  priority = false,
  style
}: {
  book: CoverBook;
  className?: string;
  small?: boolean;
  size?: 'small' | 'medium' | 'large';
  priority?: boolean;
  style?: CSSProperties;
}) {
  const requestedSize = size ?? (small ? 'small' : 'medium');
  const responsiveSize = requestedSize === 'small' ? '48px' : requestedSize === 'large' ? '280px' : '180px';
  const coverUrl = useMemo(() => {
    if (book.coverUrl) return withBasePath(book.coverUrl.replace(/size=(small|medium|large)/, `size=${requestedSize}`));
    return book.id ? withBasePath(`/api/works/${book.id}/cover?size=${requestedSize}`) : '';
  }, [book.coverUrl, book.id, requestedSize]);
  const fallbackCoverUrl = withBasePath('/images/fallback-book-cover-v1.png');
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    setImageFailed(false);
  }, [coverUrl]);

  if (coverUrl && !imageFailed) {
    return (
      <div data-book-cover="true" className={cn('relative overflow-hidden rounded-2xl bg-slate-100 shadow-sm', className)} style={style}>
        <Image
          src={coverUrl}
          alt={book.title}
          fill
          sizes={responsiveSize}
          unoptimized
          className="object-cover"
          loading={priority ? 'eager' : 'lazy'}
          priority={priority}
          onError={() => setImageFailed(true)}
        />
      </div>
    );
  }

  return (
    <div data-book-cover="true" className={cn('relative overflow-hidden rounded-2xl bg-[#252421] shadow-sm', className)} style={style}>
      <Image
        src={fallbackCoverUrl}
        alt={`${book.title}的缺省封面`}
        fill
        sizes={responsiveSize}
        className="object-cover"
        loading={priority ? 'eager' : 'lazy'}
        priority={priority}
      />
    </div>
  );
}
