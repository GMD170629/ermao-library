import { useState, type ReactNode } from 'react';
import {
  Modal,
  Pressable,
  StyleSheet,
  View,
} from 'react-native';

import { useI18n } from '../../../shared/i18n/public';
import {
  AppButton,
  AppIcon,
  AppText,
  AppTextField,
  IconButton,
  InlineNotice,
  LoadingState,
  PageHeader,
  ScreenScaffold,
  SurfaceCard,
  useAppTheme,
} from '../../../shared/ui/public';
import type {
  CollectionDetailState,
  LibraryBook,
  LibraryView,
  ShelfOverviewState,
  ShelfSummary,
} from '../model/library';
import type { ShelfMutationOutcome } from '../application/ports';
import {
  BookCover,
  ViewSwitcher,
  type LibraryCoverSource,
} from './library-primitives';

export type BookshelfScreenProps = Readonly<{
  collection: CollectionDetailState;
  coverSource?(book: LibraryBook): LibraryCoverSource;
  onCloseCollection(): void;
  onCreateShelf(name: string): Promise<ShelfMutationOutcome>;
  onDeleteShelf(shelfId: string): Promise<ShelfMutationOutcome>;
  onImport(): void;
  onOpenAllBooks(): void;
  onOpenCollection(collectionId: string): void;
  onOpenShelf(shelf: ShelfSummary): void;
  onRefresh(): void;
  onRenameShelf(
    shelfId: string,
    name: string,
  ): Promise<ShelfMutationOutcome>;
  onRetry(): void;
  onViewChange(view: LibraryView): void;
  state: ShelfOverviewState;
  view: LibraryView;
}>;

export function BookshelfScreen({
  collection,
  coverSource,
  onCloseCollection,
  onCreateShelf,
  onDeleteShelf,
  onImport,
  onOpenAllBooks,
  onOpenCollection,
  onOpenShelf,
  onRefresh,
  onRenameShelf,
  onRetry,
  onViewChange,
  state,
  view,
}: BookshelfScreenProps): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();
  const [modalShelf, setModalShelf] = useState<ShelfSummary | 'create' | null>(
    null,
  );

  if (collection.phase !== 'idle') {
    return (
      <CollectionScreen
        collection={collection}
        onBack={onCloseCollection}
        onOpenCollection={onOpenCollection}
        onOpenShelf={onOpenShelf}
        view={view}
        {...(coverSource === undefined ? {} : { coverSource })}
      />
    );
  }

  return (
    <>
      <ScreenScaffold
        contentStyle={{ gap: theme.spacing.xl }}
        edges={[]}
        onRefresh={onRefresh}
        refreshing={state.phase === 'ready' && state.refreshing}
        testID="bookshelf-screen"
      >
        <PageHeader
          description={t('library.shelves.subtitle')}
          title={t('library.shelves.title')}
          trailing={
            <IconButton
              accessibilityHint={t('library.shelves.addHint')}
              accessibilityLabel={t('library.shelves.add')}
              icon={
                <AppIcon
                  color={theme.colors.tint}
                  decorative
                  name="plus"
                  size={theme.control.iconLarge}
                />
              }
              onPress={() => setModalShelf('create')}
              tone="tint"
            />
          }
        />
        <View style={styles.toolbar}>
          <Pressable
            accessibilityLabel={t('library.shelves.allBooks')}
            accessibilityRole="button"
            hitSlop={4}
            onPress={onOpenAllBooks}
            style={({ pressed }) => [
              styles.allBooks,
              { minHeight: theme.control.minimumTouchTarget },
              pressed && { opacity: 0.68 },
            ]}
          >
            <AppText style={{ color: theme.colors.tint }} variant="label">
              {t('library.shelves.allBooks')}
            </AppText>
            <AppIcon
              color={theme.colors.tint}
              decorative
              name="chevron-right"
              size={theme.control.iconSmall}
            />
          </Pressable>
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
              onEditShelf={setModalShelf}
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

      {modalShelf === null ? null : (
        <ShelfActionModal
          busy={
            state.phase === 'ready' && state.mutatingShelfId !== null
          }
          onClose={() => setModalShelf(null)}
          onCreate={onCreateShelf}
          onDelete={onDeleteShelf}
          onImport={() => {
            setModalShelf(null);
            onImport();
          }}
          onRename={onRenameShelf}
          shelf={modalShelf}
        />
      )}
    </>
  );
}

function CollectionScreen({
  collection,
  coverSource,
  onBack,
  onOpenCollection,
  onOpenShelf,
  view,
}: Readonly<{
  collection: Exclude<CollectionDetailState, Readonly<{ phase: 'idle' }>>;
  coverSource?: (book: LibraryBook) => LibraryCoverSource;
  onBack(): void;
  onOpenCollection(collectionId: string): void;
  onOpenShelf(shelf: ShelfSummary): void;
  view: LibraryView;
}>): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();
  const title =
    collection.phase === 'ready'
      ? collection.data.name
      : t('library.shelves.collectionTitle');
  return (
    <ScreenScaffold
      contentStyle={{ gap: theme.spacing.xl }}
      edges={[]}
      testID="library-collection-screen"
    >
      <PageHeader
        backAccessibilityHint={t('library.shelves.collectionBackHint')}
        backLabel={t('common.back')}
        onBack={onBack}
        title={title}
      />
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
  onEdit?: () => void;
  onPress(): void;
  shelf: ShelfSummary;
  variant: 'collection' | LibraryView;
}>;

function ShelfVisual({
  busy,
  coverSource,
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
      <Pressable
        accessibilityLabel={label}
        accessibilityRole="button"
        accessibilityState={{ busy }}
        disabled={busy}
        onPress={onPress}
        style={({ pressed }) => [
          variant === 'grid' ? styles.tileBody : styles.railBody,
          { gap: theme.spacing.sm },
          pressed && { opacity: 0.68 },
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
      </Pressable>
      {onEdit === undefined ? null : (
        <View style={styles.editButton}>
          <IconButton
            accessibilityHint={t('library.shelves.editHint')}
            accessibilityLabel={t('library.shelves.edit', {
              name: shelf.name,
            })}
            accessibilityState={{ busy }}
            disabled={busy}
            icon={
              <AppIcon
                color={theme.colors.textMuted}
                decorative
                name="more"
                size={theme.control.iconMedium}
              />
            }
            onPress={onEdit}
          />
        </View>
      )}
    </SurfaceCard>
  );
}

type ShelfActionModalProps = Readonly<{
  busy: boolean;
  onClose(): void;
  onCreate(name: string): Promise<ShelfMutationOutcome>;
  onDelete(shelfId: string): Promise<ShelfMutationOutcome>;
  onImport(): void;
  onRename(
    shelfId: string,
    name: string,
  ): Promise<ShelfMutationOutcome>;
  shelf: ShelfSummary | 'create';
}>;

function ShelfActionModal({
  busy,
  onClose,
  onCreate,
  onDelete,
  onImport,
  onRename,
  shelf,
}: ShelfActionModalProps): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();
  const [name, setName] = useState(
    typeof shelf === 'object' ? shelf.name : '',
  );
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [mutationFailed, setMutationFailed] = useState(false);
  const editingShelf = typeof shelf === 'object' ? shelf : null;
  const normalizedName = name.trim();
  const invalidName = normalizedName.length === 0;

  return (
    <Modal
      animationType="fade"
      onRequestClose={onClose}
      presentationStyle="overFullScreen"
      statusBarTranslucent
      transparent
      visible
    >
      <View
        accessibilityViewIsModal
        style={[
          styles.modalBackdrop,
          {
            backgroundColor: theme.colors.overlay,
            padding: theme.spacing.lg,
          },
        ]}
      >
        <SurfaceCard
          accessibilityLabel={
            editingShelf === null
              ? t('library.shelves.modalTitle')
              : t('library.shelves.editTitle')
          }
          style={[
            styles.modalCard,
            { maxWidth: theme.breakpoint.contentMaxWidth },
          ]}
        >
          <View style={styles.modalHeader}>
            <AppText accessibilityRole="header" variant="title">
              {confirmDelete
                ? t('library.shelves.deleteTitle')
                : editingShelf === null
                  ? t('library.shelves.modalTitle')
                  : t('library.shelves.editTitle')}
            </AppText>
            <IconButton
              accessibilityLabel={t('common.cancel')}
              disabled={busy}
              icon={
                <AppIcon
                  color={theme.colors.textMuted}
                  decorative
                  name="close"
                  size={theme.control.iconMedium}
                />
              }
              onPress={onClose}
            />
          </View>

          {confirmDelete && editingShelf !== null ? (
            <View style={{ gap: theme.spacing.lg }}>
              {mutationFailed ? <ShelfMutationNotice /> : null}
              <AppText>
                {t('library.shelves.deleteBody', {
                  name: editingShelf.name,
                })}
              </AppText>
              <View style={[styles.modalActions, { gap: theme.spacing.sm }]}>
                <AppButton
                  disabled={busy}
                  label={t('common.cancel')}
                  onPress={() => setConfirmDelete(false)}
                  variant="secondary"
                />
                <AppButton
                  disabled={busy}
                  label={t('library.shelves.deleteAction')}
                  onPress={() => {
                    setMutationFailed(false);
                    void onDelete(editingShelf.id).then((outcome) => {
                      if (outcome.outcome === 'succeeded') onClose();
                      else setMutationFailed(true);
                    });
                  }}
                  variant="destructive"
                />
              </View>
            </View>
          ) : (
            <View style={{ gap: theme.spacing.lg }}>
              {mutationFailed ? <ShelfMutationNotice /> : null}
              <AppTextField
                autoCapitalize="sentences"
                autoCorrect
                disabled={busy}
                error={
                  invalidName && name.length > 0
                    ? t('library.shelves.nameRequired')
                    : undefined
                }
                label={t('library.shelves.nameLabel')}
                maxLength={100}
                onChangeText={setName}
                onSubmitEditing={() => {
                  if (invalidName) return;
                  setMutationFailed(false);
                  const operation =
                    editingShelf === null
                      ? onCreate(normalizedName)
                      : onRename(editingShelf.id, normalizedName);
                  void operation.then((outcome) => {
                    if (outcome.outcome === 'succeeded') onClose();
                    else setMutationFailed(true);
                  });
                }}
                placeholder={t('library.shelves.namePlaceholder')}
                returnKeyType="done"
                value={name}
              />
              <AppButton
                disabled={invalidName || busy}
                label={
                  editingShelf === null
                    ? t('library.shelves.createAction')
                    : t('library.shelves.renameAction')
                }
                loading={busy}
                onPress={() => {
                  setMutationFailed(false);
                  const operation =
                    editingShelf === null
                      ? onCreate(normalizedName)
                      : onRename(editingShelf.id, normalizedName);
                  void operation.then((outcome) => {
                    if (outcome.outcome === 'succeeded') onClose();
                    else setMutationFailed(true);
                  });
                }}
              />
              {editingShelf === null ? (
                <AppButton
                  label={t('library.import.action')}
                  leadingIcon={
                    <AppIcon
                      color={theme.colors.tint}
                      decorative
                      name="upload"
                      size={theme.control.iconMedium}
                    />
                  }
                  onPress={onImport}
                  variant="ghost"
                />
              ) : (
                <AppButton
                  disabled={busy}
                  label={t('library.shelves.deleteAction')}
                  onPress={() => setConfirmDelete(true)}
                  variant="destructive"
                />
              )}
            </View>
          )}
        </SurfaceCard>
      </View>
    </Modal>
  );
}

function ShelfMutationNotice(): ReactNode {
  const { t } = useI18n();
  return (
    <InlineNotice
      body={t('library.issue.shelfMutation')}
      title={t('library.issue.title')}
      tone="danger"
    />
  );
}

const styles = StyleSheet.create({
  allBooks: {
    alignItems: 'center',
    flexDirection: 'row',
  },
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
  modalActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
  },
  modalBackdrop: {
    alignItems: 'center',
    flex: 1,
    justifyContent: 'center',
  },
  modalCard: {
    width: '100%',
  },
  modalHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
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
