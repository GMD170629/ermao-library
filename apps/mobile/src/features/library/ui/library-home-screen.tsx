import type { ReactNode } from 'react';
import {
  Image,
  ScrollView,
  StyleSheet,
  View,
  useWindowDimensions,
} from 'react-native';

import { useI18n } from '../../../shared/i18n/public';
import {
  AppButton,
  AppIcon,
  AppText,
  ContentPressable,
  InlineNotice,
  LoadingState,
  PageIntro,
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
  BookCover,
  LibrarySearchButton,
  type LibraryCoverSource,
} from './library-primitives';

const BOOKSHELF_LEDGE_LEFT = require('../../../../assets/ui/bookshelf-ledge-left-v2.png');
const BOOKSHELF_LEDGE_CENTER = require('../../../../assets/ui/bookshelf-ledge-center-v2.png');
const BOOKSHELF_LEDGE_RIGHT = require('../../../../assets/ui/bookshelf-ledge-right-v2.png');
const SHELF_LEDGE_HEIGHT = 17;
const SHELF_LEDGE_TOP_CAP_HEIGHT = 6;
const SHELF_COVER_INSET = Math.round(SHELF_LEDGE_TOP_CAP_HEIGHT / 2);

export type LibraryHomeScreenProps = Readonly<{
  coverSource?(book: LibraryBook): LibraryCoverSource;
  importState: ImportState;
  onContinueReading(book: ContinueReadingBook): void;
  onImport(): void;
  onOpenBooks(): void;
  onOpenRecentBooks(): void;
  onOpenRecentReading(): void;
  onRefresh(): void;
  onRetry(): void;
  state: HomeState;
}>;

export function LibraryHomeScreen({
  coverSource,
  importState,
  onContinueReading,
  onImport,
  onOpenBooks,
  onOpenRecentBooks,
  onOpenRecentReading,
  onRefresh,
  onRetry,
  state,
}: LibraryHomeScreenProps): ReactNode {
  const theme = useAppTheme();
  const { formatNumber, t } = useI18n();
  const readyData = state.phase === 'ready' ? state.data : null;
  const empty =
    readyData !== null &&
    readyData.continueReading === null &&
    readyData.recentReading.length === 0 &&
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
      <PageIntro description={description} />
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
            <View style={{ gap: theme.spacing.md }}>
              <SectionHeader
                actionLabel={t('library.home.seeAll')}
                onAction={onOpenRecentReading}
                title={t('library.home.continue')}
              />
              <ContinueReadingPanel
                book={state.data.continueReading}
                {...(coverSource === undefined
                  ? {}
                  : {
                      coverSource: coverSource(
                        state.data.continueReading,
                      ),
                    })}
                onContinue={onContinueReading}
              />
            </View>
          )}
          {state.data.recentReading.length === 0 ? null : (
            <View style={{ gap: theme.spacing.md }}>
              <SectionHeader
                actionLabel={t('library.home.seeAll')}
                onAction={onOpenRecentReading}
                title={t('library.home.recentReading')}
              />
              <BookshelfRail
                books={state.data.recentReading}
                title={t('library.home.recentReading')}
                {...(coverSource === undefined ? {} : { coverSource })}
              />
            </View>
          )}
          {state.data.recentBooks.length === 0 ? null : (
            <View style={{ gap: theme.spacing.md }}>
              <SectionHeader
                actionLabel={t('library.home.seeAll')}
                onAction={onOpenRecentBooks}
                title={t('library.home.recent')}
              />
              <BookshelfRail
                books={state.data.recentBooks}
                title={t('library.home.recent')}
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
        iconName="upload"
        label={t('library.import.action')}
        onPress={onImport}
      />
    </SurfaceCard>
  );
}

type ContinueReadingPanelProps = Readonly<{
  book: ContinueReadingBook;
  coverSource?: LibraryCoverSource;
  onContinue(book: ContinueReadingBook): void;
}>;

function ContinueReadingPanel({
  book,
  coverSource,
  onContinue,
}: ContinueReadingPanelProps): ReactNode {
  const theme = useAppTheme();
  const { formatNumber, t } = useI18n();
  const { fontScale } = useWindowDimensions();
  const progress = Math.max(0, Math.min(100, book.progressPercent));
  const stacked = fontScale >= 1.6;
  const actionLabel = t('library.home.continueBookAction', {
    title: book.title,
  });
  return (
    <View
      style={[
        styles.continuePanel,
        {
          borderBottomColor: theme.colors.border,
          gap: theme.spacing.lg,
          paddingBottom: theme.spacing.xl,
        },
        stacked && styles.continueColumn,
      ]}
    >
      <ContentPressable
        accessibilityHint={t('library.home.continueBookHint')}
        accessibilityLabel={actionLabel}
        accessibilityRole="button"
        onPress={() => onContinue(book)}
        style={[
          styles.continueCoverAction,
          { borderRadius: theme.radius.compact },
        ]}
      >
        <BookCover
          accessibilityLabel={t('library.book.coverLabel', {
            title: book.title,
          })}
          size="large"
          {...(coverSource === undefined
            ? {}
            : { source: coverSource })}
        />
      </ContentPressable>
      <View
        style={[
          styles.continueDetails,
          { gap: theme.spacing.md },
          stacked && styles.continueDetailsStacked,
        ]}
      >
        <ContentPressable
          accessibilityHint={t('library.home.continueBookHint')}
          accessibilityLabel={actionLabel}
          accessibilityRole="button"
          onPress={() => onContinue(book)}
          style={[
            styles.continueTitleAction,
            {
              borderRadius: theme.radius.compact,
              minHeight: theme.control.minimumTouchTarget,
            },
          ]}
        >
          <View style={styles.flex}>
            <AppText numberOfLines={2} variant="title">
              {book.title}
            </AppText>
            <AppText muted numberOfLines={1} variant="caption">
              {book.author}
            </AppText>
          </View>
          <AppIcon
            color={theme.colors.textMuted}
            decorative
            name="chevron-right"
            size={theme.control.iconMedium}
          />
        </ContentPressable>
        <View style={{ gap: theme.spacing.xxs }}>
          <AppText muted variant="caption">
            {t('library.home.progressValue', {
              progress: formatNumber(Math.round(progress)),
            })}
          </AppText>
          <ReadingProgress progress={progress} />
        </View>
      </View>
    </View>
  );
}

function ReadingProgress({
  progress,
}: Readonly<{ progress: number }>): ReactNode {
  const theme = useAppTheme();
  const { formatNumber, t } = useI18n();
  const boundedProgress = Math.max(0, Math.min(100, progress));
  return (
    <View
      accessibilityLabel={t('library.home.progressLabel', {
        progress: formatNumber(Math.round(boundedProgress)),
      })}
      accessibilityRole="progressbar"
      accessibilityValue={{ max: 100, min: 0, now: boundedProgress }}
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
            width: `${boundedProgress}%`,
          },
        ]}
      />
    </View>
  );
}

type BookshelfRailProps = Readonly<{
  books: readonly LibraryBook[];
  coverSource?(book: LibraryBook): LibraryCoverSource;
  title: string;
}>;

function BookshelfRail({
  books,
  coverSource,
  title,
}: BookshelfRailProps): ReactNode {
  const theme = useAppTheme();
  return (
    <ScrollView
      accessibilityLabel={title}
      contentContainerStyle={[
        styles.shelfScrollContent,
        { paddingRight: theme.spacing.lg },
      ]}
      horizontal
      nestedScrollEnabled
      showsHorizontalScrollIndicator={false}
    >
      <View>
        <View
          testID="home-shelf-covers"
          style={[
            styles.shelfCovers,
            { gap: theme.spacing.md, paddingTop: theme.spacing.sm },
          ]}
        >
          {books.map((book) => (
            <ShelfBookCover
              book={book}
              key={book.id}
              {...(coverSource === undefined
                ? {}
                : { coverSource: coverSource(book) })}
            />
          ))}
        </View>
        <ShelfLedge />
        <View
          testID="home-shelf-metadata-band"
          style={[
            styles.shelfMetadataBand,
            {
              borderBottomColor: theme.colors.borderStrong,
            },
          ]}
        >
          <View
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            pointerEvents="none"
            testID="home-shelf-metadata-surface"
            style={[
              styles.shelfMetadataSurface,
              { backgroundColor: theme.colors.border },
            ]}
          />
          <View
            style={styles.shelfMetadataItems}
            testID="home-shelf-metadata-items"
          >
            {books.map((book, index) => (
              <View
                key={book.id}
                style={[
                  styles.shelfMetadata,
                  {
                    borderLeftColor: theme.colors.borderStrong,
                    marginLeft: index === 0 ? 0 : theme.spacing.md,
                    paddingLeft: index === 0 ? 0 : theme.spacing.sm,
                  },
                ]}
              >
                <AppText numberOfLines={1} variant="caption">
                  {book.title}
                </AppText>
                <AppText muted numberOfLines={1} variant="caption">
                  {book.author}
                </AppText>
              </View>
            ))}
          </View>
        </View>
      </View>
    </ScrollView>
  );
}

function ShelfBookCover({
  book,
  coverSource,
}: Readonly<{
  book: LibraryBook;
  coverSource?: LibraryCoverSource;
}>): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();
  const progress = book.progressPercent;
  return (
    <View
      style={[
        styles.shelfBookCover,
        theme.elevation.floating,
        {
          backgroundColor: theme.colors.cardStrong,
          borderRadius: theme.radius.compact,
        },
      ]}
    >
      <BookCover
        accessibilityLabel={t('library.book.coverLabel', {
          title: book.title,
        })}
        size="medium"
        {...(coverSource === undefined ? {} : { source: coverSource })}
      />
      {progress === undefined || progress <= 0 ? null : (
        <View style={styles.shelfProgressOverlay}>
          <ReadingProgress progress={progress} />
        </View>
      )}
    </View>
  );
}

function ShelfLedge(): ReactNode {
  const theme = useAppTheme();
  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      testID="home-shelf-ledge"
      style={[
        styles.shelfLedge,
        theme.elevation.card,
        {
          backgroundColor: theme.colors.cardStrong,
          borderRadius: theme.radius.compact,
        },
      ]}
    >
      <Image
        source={BOOKSHELF_LEDGE_LEFT}
        style={[
          styles.shelfLedgeEnd,
          theme.isDark && styles.shelfLedgeImageDark,
        ]}
      />
      <Image
        resizeMode="stretch"
        source={BOOKSHELF_LEDGE_CENTER}
        style={[
          styles.shelfLedgeCenter,
          theme.isDark && styles.shelfLedgeImageDark,
        ]}
      />
      <Image
        source={BOOKSHELF_LEDGE_RIGHT}
        style={[
          styles.shelfLedgeEnd,
          theme.isDark && styles.shelfLedgeImageDark,
        ]}
      />
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
  return (
    <View style={styles.sectionHeader}>
      <AppText accessibilityRole="header" variant="headline">
        {title}
      </AppText>
      <AppButton
        label={actionLabel}
        onPress={onAction}
        variant="ghost"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  continueColumn: {
    flexDirection: 'column',
  },
  continueCoverAction: {
    alignSelf: 'flex-start',
    minHeight: 44,
    minWidth: 44,
  },
  continueDetails: {
    flex: 1,
    justifyContent: 'space-between',
    minWidth: 0,
  },
  continueDetailsStacked: {
    alignSelf: 'stretch',
  },
  continuePanel: {
    alignItems: 'flex-start',
    borderBottomWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
  },
  continueTitleAction: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 8,
    justifyContent: 'space-between',
    marginHorizontal: -8,
    paddingHorizontal: 8,
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
    minWidth: 0,
  },
  progressFill: {
    height: '100%',
  },
  progressTrack: {
    overflow: 'hidden',
  },
  sectionHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  shelfBookCover: {
    width: 80,
    zIndex: 3,
  },
  shelfCovers: {
    alignItems: 'flex-end',
    flexDirection: 'row',
    paddingHorizontal: 8,
    zIndex: 3,
  },
  shelfLedge: {
    flexDirection: 'row',
    height: SHELF_LEDGE_HEIGHT,
    marginTop: -SHELF_COVER_INSET,
    zIndex: 1,
  },
  shelfLedgeCenter: {
    flex: 1,
    height: SHELF_LEDGE_HEIGHT,
  },
  shelfLedgeEnd: {
    height: SHELF_LEDGE_HEIGHT,
    width: 20,
  },
  shelfLedgeImageDark: {
    opacity: 0.56,
  },
  shelfMetadata: {
    borderLeftWidth: StyleSheet.hairlineWidth,
    gap: 2,
    justifyContent: 'center',
    minHeight: 54,
    width: 80,
  },
  shelfMetadataBand: {
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  shelfMetadataItems: {
    flexDirection: 'row',
    paddingBottom: 6,
    paddingHorizontal: 8,
  },
  shelfMetadataSurface: {
    bottom: 0,
    left: 0,
    opacity: 0.38,
    position: 'absolute',
    right: 0,
    top: 0,
  },
  shelfProgressOverlay: {
    bottom: SHELF_COVER_INSET + 2,
    left: 4,
    position: 'absolute',
    right: 4,
  },
  shelfScrollContent: {
    flexGrow: 1,
  },
});
