import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

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
  SystemActionMenu,
  useAppTheme,
} from '../../../shared/ui/public';
import type {
  CollectionDetailState,
  LibraryBook,
  LibraryView,
  ShelfOverviewState,
  ShelfSummary,
} from '../model/library';
import {
  BookCover,
  ViewSwitcher,
  type LibraryCoverSource,
} from './library-primitives';

export type BookshelfScreenProps = Readonly<{
  coverSource?(book: LibraryBook): LibraryCoverSource;
  onCreateShelf(): void;
  onDeleteShelf(shelf: ShelfSummary): void;
  onEditShelf(shelf: ShelfSummary): void;
  onImport(): void;
  onOpenAllBooks(): void;
  onOpenCollection(collectionId: string): void;
  onOpenShelf(shelf: ShelfSummary): void;
  onRefresh(): void;
  onRetry(): void;
  onViewChange(view: LibraryView): void;
  state: ShelfOverviewState;
  view: LibraryView;
}>;

export function BookshelfScreen({
  coverSource,
  onCreateShelf,
  onDeleteShelf,
  onEditShelf,
  onImport,
  onOpenAllBooks,
  onOpenCollection,
  onOpenShelf,
  onRefresh,
  onRetry,
  onViewChange,
  state,
  view,
}: BookshelfScreenProps): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();

  return (
    <ScreenScaffold
        contentStyle={{ gap: theme.spacing.xl }}
        edges={[]}
        onRefresh={onRefresh}
        refreshing={state.phase === 'ready' && state.refreshing}
        testID="bookshelf-screen"
      >
        <PageIntro description={t('library.shelves.subtitle')} />
        <View style={styles.toolbar}>
          <AppButton
            iconName="library"
            label={t('library.shelves.allBooks')}
            onPress={onOpenAllBooks}
            variant="ghost"
          />
          <SystemActionMenu
            accessibilityLabel={t('library.shelves.add')}
            actions={[
              {
                id: 'create',
                title: t('library.shelves.createAction'),
              },
              { id: 'import', title: t('library.import.action') },
            ]}
            iconName="plus"
            onAction={(actionId) => {
              if (actionId === 'create') onCreateShelf();
              if (actionId === 'import') onImport();
            }}
          />
          <ViewSwitcher
            gridLabel={t('library.view.grid')}
            listLabel={t('library.view.list')}
            onChange={onViewChange}
            value={view}
          />
        </View>

        {state.phase === 'idle' || state.phase === 'loading' ? (
          <LoadingState label={t('library.shelves.loading')} />
        ) : state.phase === 'failure' ? (
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
        ) : (
          <View style={{ gap: theme.spacing.xxl }}>
            {state.warning === undefined ? null : (
              <InlineNotice
                body={t('library.issue.shelfMutation')}
                title={t('library.issue.title')}
                tone="warning"
              />
            )}
            <ShelfSection
              emptyBody={t('library.shelves.collectionsEmpty')}
              onOpenShelf={(shelf) => onOpenCollection(shelf.id)}
              shelves={state.data.collections}
              title={t('library.shelves.collections')}
              variant="collection"
              view={view}
              {...(coverSource === undefined ? {} : { coverSource })}
            />
            <ShelfSection
              emptyBody={t('library.shelves.empty')}
              mutatingShelfId={state.mutatingShelfId}
              onDeleteShelf={onDeleteShelf}
              onEditShelf={onEditShelf}
              onOpenShelf={onOpenShelf}
              shelves={state.data.shelves}
              title={t('library.shelves.section')}
              variant="shelf"
              view={view}
              {...(coverSource === undefined ? {} : { coverSource })}
            />
          </View>
        )}
    </ScreenScaffold>
  );
}

export function LibraryCollectionScreen({
  collection,
  coverSource,
  onOpenCollection,
  onOpenShelf,
  view,
}: Readonly<{
  collection: Exclude<CollectionDetailState, Readonly<{ phase: 'idle' }>>;
  coverSource?: (book: LibraryBook) => LibraryCoverSource;
  onOpenCollection(collectionId: string): void;
  onOpenShelf(shelf: ShelfSummary): void;
  view: LibraryView;
}>): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();
  return (
    <ScreenScaffold
      contentStyle={{ gap: theme.spacing.xl }}
      edges={[]}
      testID="library-collection-screen"
    >
      <PageIntro description={t('library.shelves.collectionMembers')} />
      {collection.phase === 'loading' ? (
        <LoadingState label={t('library.shelves.collectionLoading')} />
      ) : collection.phase === 'failure' ? (
        <View style={{ gap: theme.spacing.md }}>
          <InlineNotice
            body={t('library.issue.loadBody')}
            title={t('library.issue.title')}
            tone="danger"
          />
          <AppButton
            label={t('common.retry')}
            onPress={() => onOpenCollection(collection.collectionId)}
            variant="secondary"
          />
        </View>
      ) : (
        <ShelfSection
          emptyBody={t('library.shelves.collectionMembersEmpty')}
          onOpenShelf={onOpenShelf}
          shelves={collection.data.shelves}
          title={t('library.shelves.collectionMembers')}
          variant="shelf"
          view={view}
          {...(coverSource === undefined ? {} : { coverSource })}
        />
      )}
    </ScreenScaffold>
  );
}

type ShelfSectionProps = Readonly<{
  coverSource?: (book: LibraryBook) => LibraryCoverSource;
  emptyBody: string;
  mutatingShelfId?: string | null;
  onDeleteShelf?: (shelf: ShelfSummary) => void;
  onEditShelf?: (shelf: ShelfSummary) => void;
  onOpenShelf(shelf: ShelfSummary): void;
  shelves: readonly ShelfSummary[];
  title: string;
  variant: 'collection' | 'shelf';
  view: LibraryView;
}>;

function ShelfSection({
  coverSource,
  emptyBody,
  mutatingShelfId,
  onDeleteShelf,
  onEditShelf,
  onOpenShelf,
  shelves,
  title,
  variant,
  view,
}: ShelfSectionProps): ReactNode {
  const theme = useAppTheme();
  return (
    <View style={{ gap: theme.spacing.md }}>
      <AppText accessibilityRole="header" variant="headline">
        {title}
      </AppText>
      {shelves.length === 0 ? (
        <AppText muted>{emptyBody}</AppText>
      ) : (
        <View
          style={[
            view === 'grid' && styles.shelfGrid,
            { gap: theme.spacing.md },
          ]}
        >
          {shelves.map((shelf) => (
            <ShelfVisual
              busy={mutatingShelfId === shelf.id}
              key={shelf.id}
              onPress={() => onOpenShelf(shelf)}
              shelf={shelf}
              variant={variant === 'collection' ? 'collection' : view}
              {...(coverSource === undefined ? {} : { coverSource })}
              {...(onEditShelf === undefined
                ? {}
                : { onEdit: () => onEditShelf(shelf) })}
              {...(onDeleteShelf === undefined
                ? {}
                : { onDelete: () => onDeleteShelf(shelf) })}
            />
          ))}
        </View>
      )}
    </View>
  );
}

type ShelfVisualProps = Readonly<{
  busy: boolean;
  coverSource?: (book: LibraryBook) => LibraryCoverSource;
  onDelete?: () => void;
  onEdit?: () => void;
  onPress(): void;
  shelf: ShelfSummary;
  variant: 'collection' | LibraryView;
}>;

function ShelfVisual({
  busy,
  coverSource,
  onDelete,
  onEdit,
  onPress,
  shelf,
  variant,
}: ShelfVisualProps): ReactNode {
  const theme = useAppTheme();
  const { formatNumber, t } = useI18n();
  const preview = shelf.books.slice(0, variant === 'grid' ? 2 : 3);
  const label =
    variant === 'collection'
      ? t('library.shelves.collectionItemLabel', {
          count: formatNumber(shelf.shelfCount),
          name: shelf.name,
        })
      : t('library.shelves.itemLabel', {
          count: formatNumber(shelf.bookCount),
          name: shelf.name,
        });
  return (
    <SurfaceCard
      padding="compact"
      style={variant === 'grid' ? styles.shelfTile : undefined}
    >
      <ContentPressable
        accessibilityLabel={label}
        accessibilityRole="button"
        accessibilityState={{ busy }}
        disabled={busy}
        onPress={onPress}
        style={[
          variant === 'grid' ? styles.tileBody : styles.railBody,
          { gap: theme.spacing.sm },
        ]}
      >
        <View style={[styles.coverRail, { gap: theme.spacing.xs }]}>
          {preview.length === 0 ? (
            <View
              style={[
                styles.shelfPlaceholder,
                {
                  backgroundColor: theme.colors.tintMuted,
                  borderRadius: theme.radius.compact,
                  height: theme.control.regularHeight * 2,
                },
              ]}
            >
              <AppIcon
                color={theme.colors.tint}
                decorative
                name="library"
                size={theme.control.iconLarge}
              />
            </View>
          ) : (
            preview.map((book) => (
              <BookCover
                accessibilityLabel={t('library.book.coverLabel', {
                  title: book.title,
                })}
                key={book.id}
                size="small"
                {...(coverSource === undefined ||
                coverSource(book) === undefined
                  ? {}
                  : { source: coverSource(book) })}
              />
            ))
          )}
        </View>
        <View style={[styles.flex, { gap: theme.spacing.xxs }]}>
          <AppText numberOfLines={2} variant="label">
            {shelf.name}
          </AppText>
          <AppText muted variant="caption">
            {variant === 'collection'
              ? t('library.shelves.collectionCount', {
                  count: formatNumber(shelf.shelfCount),
                })
              : t('library.shelves.bookCount', {
                  count: formatNumber(shelf.bookCount),
                })}
          </AppText>
        </View>
      </ContentPressable>
      {onEdit === undefined ? null : (
        <View style={styles.editButton}>
          <SystemActionMenu
            accessibilityLabel={t('library.shelves.edit', {
              name: shelf.name,
            })}
            actions={[
              { id: 'edit', title: t('library.shelves.renameAction') },
              {
                destructive: true,
                id: 'delete',
                title: t('library.shelves.deleteAction'),
              },
            ]}
            iconName="more"
            onAction={(actionId) => {
              if (actionId === 'edit') onEdit();
              if (actionId === 'delete') onDelete?.();
            }}
          />
        </View>
      )}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  coverRail: {
    flexDirection: 'row',
    minHeight: 72,
  },
  editButton: {
    position: 'absolute',
    right: 8,
    top: 8,
  },
  flex: {
    flex: 1,
  },
  railBody: {
    alignItems: 'center',
    flexDirection: 'row',
    paddingRight: 48,
  },
  shelfGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  shelfPlaceholder: {
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
  },
  shelfTile: {
    minWidth: 156,
    width: '47%',
  },
  tileBody: {
    paddingRight: 48,
  },
  toolbar: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
});
