import { useState, type ReactNode } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { useI18n } from '../../../shared/i18n/public';
import {
  AppButton,
  AppIcon,
  AppText,
  IconButton,
  InlineNotice,
  LoadingState,
  PageHeader,
  ScreenScaffold,
  SurfaceCard,
  useAppTheme,
} from '../../../shared/ui/public';
import type {
  ContinueReadingBook,
  HomeState,
  ImportState,
  LibraryBook,
} from '../model/library';
import {
  BookCollection,
  BookCover,
  LibrarySearchButton,
  type LibraryCoverSource,
} from './library-primitives';

export type LibraryHomeScreenProps = Readonly<{
  coverSource?(book: LibraryBook): LibraryCoverSource;
  importState: ImportState;
  onImport(): void;
  onOpenBooks(): void;
  onRefresh(): void;
  onRetry(): void;
  onToggleTheme(): void;
  state: HomeState;
  themeMode: 'dark' | 'light';
}>;

export function LibraryHomeScreen({
  coverSource,
  importState,
  onImport,
  onOpenBooks,
  onRefresh,
  onRetry,
  onToggleTheme,
  state,
  themeMode,
}: LibraryHomeScreenProps): ReactNode {
  const theme = useAppTheme();
  const { formatNumber, t } = useI18n();
  const [readingUnavailable, setReadingUnavailable] = useState(false);
  const readyData = state.phase === 'ready' ? state.data : null;
  const empty =
    readyData !== null &&
    readyData.continueReading === null &&
    readyData.recentBooks.length === 0 &&
    (readyData.summary?.totalBooks ?? 0) === 0;
  const description =
    readyData === null
      ? t('library.home.fallbackSubtitle')
      : empty
        ? t('library.home.emptyTitle')
        : readyData.summary === null
          ? t('library.home.fallbackSubtitle')
          : t('library.home.summary', {
              total: formatNumber(readyData.summary.totalBooks),
              unread: formatNumber(readyData.summary.unreadBooks),
            });

  return (
    <ScreenScaffold
      contentStyle={{ gap: theme.spacing.xl }}
      edges={[]}
      onRefresh={onRefresh}
      refreshing={state.phase === 'ready' && state.refreshing}
      testID="library-home-screen"
    >
      <PageHeader
        description={description}
        title={t('library.home.title')}
        trailing={
          <IconButton
            accessibilityHint={t('library.home.themeHint')}
            accessibilityLabel={
              themeMode === 'dark'
                ? t('library.home.useLightTheme')
                : t('library.home.useDarkTheme')
            }
            accessibilityState={{ selected: themeMode === 'dark' }}
            icon={
              <AppIcon
                color={theme.colors.tint}
                decorative
                name="sun"
                size={theme.control.iconLarge}
              />
            }
            onPress={onToggleTheme}
            tone="tint"
          />
        }
      />
      <LibrarySearchButton
        accessibilityHint={t('library.search.hint')}
        label={t('library.search.placeholder')}
        onPress={onOpenBooks}
      />
      <BackgroundImportNotice state={importState} />

      {state.phase === 'idle' || state.phase === 'loading' ? (
        <LoadingState label={t('library.home.loading')} />
      ) : state.phase === 'failure' ? (
        <FailureState onRetry={onRetry} />
      ) : empty ? (
        <EmptyHome onImport={onImport} />
      ) : (
        <View style={{ gap: theme.spacing.xxl }}>
          {state.warning === undefined &&
          state.data.unavailableSections.length === 0 ? null : (
            <InlineNotice
              body={t('library.issue.partial')}
              title={t('library.issue.title')}
              tone="warning"
            />
          )}
          {state.data.continueReading === null ? null : (
            <ContinueReadingCard
              book={state.data.continueReading}
              {...(coverSource === undefined
                ? {}
                : {
                    coverSource: coverSource(
                      state.data.continueReading,
                    ),
                  })}
              onContinue={() => setReadingUnavailable(true)}
            />
          )}
          {readingUnavailable ? (
            <InlineNotice
              body={t('library.reader.unavailableBody')}
              title={t('library.reader.unavailableTitle')}
            />
          ) : null}
          {state.data.recentBooks.length === 0 ? null : (
            <View style={{ gap: theme.spacing.md }}>
              <SectionHeader
                actionLabel={t('library.home.seeAll')}
                onAction={onOpenBooks}
                title={t('library.home.recent')}
              />
              <BookCollection
                books={state.data.recentBooks.slice(0, 3)}
                coverAccessibilityLabel={(book) =>
                  t('library.book.coverLabel', { title: book.title })
                }
                emptyLabel={t('library.books.empty')}
                view="grid"
                {...(coverSource === undefined ? {} : { coverSource })}
              />
            </View>
          )}
        </View>
      )}
    </ScreenScaffold>
  );
}

function BackgroundImportNotice({
  state,
}: Readonly<{ state: ImportState }>): ReactNode {
  const { formatNumber, t } = useI18n();
  if (state.phase !== 'ready') return null;
  if (state.upload.phase === 'uploading') {
    return (
      <InlineNotice
        body={t('library.import.backgroundUploadingBody', {
          completed: formatNumber(state.upload.completedFiles),
          total: formatNumber(state.upload.totalFiles),
        })}
        title={t('library.import.backgroundUploadingTitle')}
      />
    );
  }
  if (
    state.upload.phase !== 'succeeded' ||
    !state.upload.result.autoImport
  ) {
    return null;
  }
  return (
    <InlineNotice
      body={t('library.import.backgroundProcessingBody', {
        count: formatNumber(state.upload.result.saved),
      })}
      title={t('library.import.successTitle')}
    />
  );
}

function FailureState({ onRetry }: Readonly<{ onRetry(): void }>): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();
  return (
    <View style={{ gap: theme.spacing.md }}>
      <InlineNotice
        body={t('library.issue.loadBody')}
        title={t('library.issue.title')}
        tone="danger"
      />
      <AppButton
        label={t('common.retry')}
        onPress={onRetry}
        variant="secondary"
      />
    </View>
  );
}

function EmptyHome({ onImport }: Readonly<{ onImport(): void }>): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();
  return (
    <SurfaceCard
      accessibilityLabel={t('library.home.emptyTitle')}
      style={[styles.emptyCard, { gap: theme.spacing.lg }]}
    >
      <View
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        style={[
          styles.emptyIllustration,
          {
            backgroundColor: theme.colors.tintMuted,
            borderRadius: theme.radius.spacious,
            height: theme.spacing.xxxl * 3,
            width: theme.spacing.xxxl * 3,
          },
        ]}
      >
        <AppIcon
          color={theme.colors.tint}
          decorative
          name="library"
          size={theme.control.regularHeight}
        />
      </View>
      <View style={{ gap: theme.spacing.xs }}>
        <AppText accessibilityRole="header" variant="title">
          {t('library.home.emptyTitle')}
        </AppText>
        <AppText muted>{t('library.home.emptyBody')}</AppText>
      </View>
      <AppButton
        fullWidth
        label={t('library.import.action')}
        leadingIcon={
          <AppIcon
            color={theme.colors.onAction}
            decorative
            name="upload"
            size={theme.control.iconMedium}
          />
        }
        onPress={onImport}
      />
    </SurfaceCard>
  );
}

type ContinueReadingCardProps = Readonly<{
  book: ContinueReadingBook;
  coverSource?: LibraryCoverSource;
  onContinue(): void;
}>;

function ContinueReadingCard({
  book,
  coverSource,
  onContinue,
}: ContinueReadingCardProps): ReactNode {
  const theme = useAppTheme();
  const { formatNumber, t } = useI18n();
  const progress = Math.max(0, Math.min(100, book.progressPercent));
  return (
    <View style={{ gap: theme.spacing.md }}>
      <AppText accessibilityRole="header" variant="headline">
        {t('library.home.continue')}
      </AppText>
      <SurfaceCard padding="compact">
        <View style={[styles.continueRow, { gap: theme.spacing.md }]}>
          <BookCover
            accessibilityLabel={t('library.book.coverLabel', {
              title: book.title,
            })}
            size="large"
            {...(coverSource === undefined
              ? {}
              : { source: coverSource })}
          />
          <View style={[styles.flex, { gap: theme.spacing.sm }]}>
            <View style={{ gap: theme.spacing.xxs }}>
              <AppText numberOfLines={2} variant="headline">
                {book.title}
              </AppText>
              <AppText muted numberOfLines={1} variant="caption">
                {book.author}
              </AppText>
            </View>
            <AppText muted numberOfLines={2} variant="caption">
              {book.chapter ??
                book.volumeTitle ??
                t('library.home.continueFallback')}
            </AppText>
            <View style={{ gap: theme.spacing.xs }}>
              <View
                accessibilityLabel={t('library.home.progressLabel', {
                  progress: formatNumber(Math.round(progress)),
                })}
                accessibilityRole="progressbar"
                accessibilityValue={{ max: 100, min: 0, now: progress }}
                style={[
                  styles.progressTrack,
                  {
                    backgroundColor: theme.colors.border,
                    borderRadius: theme.radius.compact,
                    height: theme.spacing.xxs,
                  },
                ]}
              >
                <View
                  style={[
                    styles.progressFill,
                    {
                      backgroundColor: theme.colors.tint,
                      borderRadius: theme.radius.compact,
                      width: `${progress}%`,
                    },
                  ]}
                />
              </View>
              <AppText muted variant="caption">
                {t('library.home.progressValue', {
                  progress: formatNumber(Math.round(progress)),
                })}
              </AppText>
            </View>
            <AppButton
              label={t('library.home.continueAction')}
              leadingIcon={
                <AppIcon
                  color={theme.colors.onAction}
                  decorative
                  name="play"
                  size={theme.control.iconMedium}
                />
              }
              onPress={onContinue}
            />
          </View>
        </View>
      </SurfaceCard>
    </View>
  );
}

function SectionHeader({
  actionLabel,
  onAction,
  title,
}: Readonly<{
  actionLabel: string;
  onAction(): void;
  title: string;
}>): ReactNode {
  const theme = useAppTheme();
  return (
    <View style={styles.sectionHeader}>
      <AppText accessibilityRole="header" variant="headline">
        {title}
      </AppText>
      <Pressable
        accessibilityLabel={actionLabel}
        accessibilityRole="button"
        hitSlop={8}
        onPress={onAction}
        style={({ pressed }) => [
          styles.sectionAction,
          { minHeight: theme.control.minimumTouchTarget },
          pressed && { opacity: 0.68 },
        ]}
      >
        <AppText style={{ color: theme.colors.tint }} variant="label">
          {actionLabel}
        </AppText>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  continueRow: {
    alignItems: 'flex-start',
    flexDirection: 'row',
  },
  emptyCard: {
    alignItems: 'center',
  },
  emptyIllustration: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  flex: {
    flex: 1,
  },
  progressFill: {
    height: '100%',
  },
  progressTrack: {
    overflow: 'hidden',
  },
  sectionAction: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  sectionHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
});
