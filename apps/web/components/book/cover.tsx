'use client';

import Image from 'next/image';
import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { withBasePath } from '../../lib/base-path';
import { cn } from '../ui/cn';
import { useI18n as useAttributeI18n } from '@/i18n/provider';
import type { MediaKind } from '../../types/work';

export type CoverBook = {
  id?: string | number;
  title: string;
  author: string;
  coverUrl?: string;
  format?: string;
  gradient?: string;
  coverStatus?: string;
  availableMediaKinds?: MediaKind[];
};

export function Cover({
  book,
  className = '',
  small = false,
  size,
  variant = 'contained',
  priority = false,
  style
}: {
  book: CoverBook;
  className?: string;
  small?: boolean;
  size?: 'small' | 'medium' | 'large';
  variant?: 'contained' | 'bookshelf';
  priority?: boolean;
  style?: CSSProperties;
}) {
  const { t: i18nAttribute } = useAttributeI18n();
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
    if (variant === 'bookshelf') {
      return (
        <Image
          data-book-cover="true"
          data-i18n-skip
          src={coverUrl}
          alt={book.title}
          width={600}
          height={900}
          sizes={responsiveSize}
          unoptimized
          className={cn('block h-auto max-h-[150cqw] w-auto max-w-full rounded-2xl', className)}
          style={style}
          loading={priority ? 'eager' : 'lazy'}
          priority={priority}
          onError={() => setImageFailed(true)}
        />
      );
    }

    return (
      <div
        data-book-cover="true"
        data-i18n-skip
        className={cn('relative overflow-hidden rounded-2xl bg-transparent', className)}
        style={style}
      >
        <Image
          src={coverUrl}
          alt={book.title}
          fill
          sizes={responsiveSize}
          unoptimized
          className="rounded-[inherit] object-contain object-center"
          loading={priority ? 'eager' : 'lazy'}
          priority={priority}
          onError={() => setImageFailed(true)}
        />
      </div>
    );
  }

  if (variant === 'bookshelf') {
    return (
      <Image
        data-book-cover="true"
        data-i18n-skip
        src={fallbackCoverUrl}
        alt={i18nAttribute("{value0}的缺省封面", { value0: book.title })}
        width={600}
        height={900}
        sizes={responsiveSize}
        unoptimized
        className={cn('block h-auto max-h-[150cqw] w-auto max-w-full rounded-2xl bg-[#252421] shadow-sm', className)}
        style={style}
        loading={priority ? 'eager' : 'lazy'}
        priority={priority}
      />
    );
  }

  return (
    <div data-book-cover="true" data-i18n-skip className={cn('relative overflow-hidden rounded-2xl bg-[#252421] shadow-sm', className)} style={style}>
      <Image
        src={fallbackCoverUrl}
        alt={i18nAttribute("{value0}的缺省封面", { value0: book.title })}
        fill
        sizes={responsiveSize}
        className="object-cover"
        loading={priority ? 'eager' : 'lazy'}
        priority={priority}
      />
    </div>
  );
}
