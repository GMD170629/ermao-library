import { useState, type ReactNode } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { useI18n } from '../../../shared/i18n/public';
import {
  AppButton,
  AppIcon,
  AppText,
  InlineNotice,
  LoadingState,
  PageHeader,
  ScreenScaffold,
  useAppTheme,
} from '../../../shared/ui/public';
import type {
  BooksQuery,
  BooksState,
  LibraryBook,
  LibrarySort,
} from '../model/library';
import {
  BookCollection,
  LibrarySearchField,
  ViewSwitcher,
  type LibraryCoverSource,
} from './library-primitives';

export type BooksScreenProps = Readonly<{
  coverSource?(book: LibraryBook): LibraryCoverSource;
  onBack(): void;
  onLoadNextPage(): void;
  onQueryChange(query: BooksQuery): void;
  onRefresh(): void;
  onRetry(): void;
  shelfName?: string;
  state: BooksState;
}>;

export function BooksScreen({
  coverSource,
  onBack,
  onLoadNextPage,
  onQueryChange,
  onRefresh,
  onRetry,
  shelfName,
  state,
}: BooksScreenProps): ReactNode {
  const theme = useAppTheme();
  const { formatNumber, t } = useI18n();
  const updateQuery = (patch: Partial<BooksQuery>): void => {
    onQueryChange({ ...state.query, ...patch });
  };

  return (
    <ScreenScaffold
      contentStyle={{ gap: theme.spacing.xl }}
      edges={[]}
      onRefresh={onRefresh}
      refreshing={state.phase === 'ready' && state.refreshing}
      testID="library-books-screen"
    >
      <PageHeader
        backAccessibilityHint={t('library.books.backHint')}
        backLabel={t('common.back')}
        description={
          shelfName === undefined
            ? t('library.books.subtitle')
            : t('library.books.shelfSubtitle', { name: shelfName })
        }
        onBack={onBack}
        title={shelfName ?? t('library.books.title')}
      />
      <BooksSearchField
        key={state.query.search}
        onSubmit={(search) => updateQuery({ search })}
        query={state.query.search}
      />
      <View style={[styles.viewToolbar, { gap: theme.spacing.md }]}>
        <AppText muted style={styles.flex} variant="caption">
          {state.phase === 'ready'
            ? t('library.books.total', {
                count: formatNumber(state.total),
              })
            : t('library.books.filters')}
        </AppText>
        <ViewSwitcher
          gridLabel={t('library.view.grid')}
          listLabel={t('library.view.list')}
          onChange={(view) => updateQuery({ view })}
          value={state.query.view}
        />
      </View>

      <FilterRail
        allLabel={t('library.filter.allStatuses')}
        onSelect={(status) => updateQuery({ status })}
        options={[
          ['READING', t('library.filter.reading')],
          ['UNREAD', t('library.filter.unread')],
          ['FINISHED', t('library.filter.finished')],
        ]}
        selected={state.query.status}
      />
      <FilterRail
        allLabel={t('library.filter.allMedia')}
        onSelect={(mediaKind) => updateQuery({ mediaKind })}
        options={[
          ['EBOOK', t('library.filter.ebook')],
          ['COMIC', t('library.filter.comic')],
          ['AUDIOBOOK', t('library.filter.audiobook')],
        ]}
        selected={state.query.mediaKind}
      />
      <SortRail
        direction={state.query.direction}
        onDirectionToggle={() =>
          updateQuery({
            direction: state.query.direction === 'asc' ? 'desc' : 'asc',
          })
        }
        onSelect={(sort) => updateQuery({ sort })}
        selected={state.query.sort}
      />

      {state.phase === 'idle' || state.phase === 'loading' ? (
        <LoadingState label={t('library.books.loading')} />
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
        <View style={{ gap: theme.spacing.lg }}>
          {state.warning === undefined ? null : (
            <InlineNotice
              body={t('library.issue.partial')}
              title={t('library.issue.title')}
              tone="warning"
            />
          )}
          <BookCollection
            books={state.books}
            coverAccessibilityLabel={(book) =>
              t('library.book.coverLabel', { title: book.title })
            }
            emptyLabel={
              state.query.search.length > 0 ||
              state.query.status !== null ||
              state.query.mediaKind !== null
                ? t('library.books.noResults')
                : t('library.books.empty')
            }
            view={state.query.view}
            {...(coverSource === undefined ? {} : { coverSource })}
          />
          {state.page >= state.totalPages ? null : (
            <AppButton
              label={t('library.books.loadMore')}
              loading={state.loadingNextPage}
              onPress={onLoadNextPage}
              variant="secondary"
            />
          )}
        </View>
      )}
    </ScreenScaffold>
  );
}

function BooksSearchField({
  onSubmit,
  query,
}: Readonly<{
  onSubmit(value: string): void;
  query: string;
}>): ReactNode {
  const { t } = useI18n();
  const [value, setValue] = useState(query);
  return (
    <LibrarySearchField
      accessibilityLabel={t('library.search.label')}
      clearAccessibilityLabel={t('library.search.clear')}
      onChangeText={setValue}
      onSubmit={() => onSubmit(value)}
      placeholder={t('library.search.placeholder')}
      value={value}
    />
  );
}

type FilterRailProps<Value extends string> = Readonly<{
  allLabel: string;
  onSelect(value: Value | null): void;
  options: readonly (readonly [Value, string])[];
  selected: Value | null;
}>;

function FilterRail<Value extends string>({
  allLabel,
  onSelect,
  options,
  selected,
}: FilterRailProps<Value>): ReactNode {
  const theme = useAppTheme();
  return (
    <ScrollView
      accessibilityRole="tablist"
      contentContainerStyle={{ gap: theme.spacing.xs }}
      horizontal
      showsHorizontalScrollIndicator={false}
    >
      <FilterChip
        label={allLabel}
        onPress={() => onSelect(null)}
        selected={selected === null}
      />
      {options.map(([value, label]) => (
        <FilterChip
          key={value}
          label={label}
          onPress={() => onSelect(value)}
          selected={selected === value}
        />
      ))}
    </ScrollView>
  );
}

function FilterChip({
  label,
  onPress,
  selected,
}: Readonly<{
  label: string;
  onPress(): void;
  selected: boolean;
}>): ReactNode {
  const theme = useAppTheme();
  return (
    <Pressable
      accessibilityLabel={label}
      accessibilityRole="tab"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={({ pressed }) => [
        styles.filterChip,
        {
          backgroundColor: selected
            ? theme.colors.tintMuted
            : theme.colors.card,
          borderColor: selected
            ? theme.colors.tint
            : theme.colors.border,
          borderRadius: theme.radius.control,
          minHeight: theme.control.minimumTouchTarget,
          paddingHorizontal: theme.spacing.md,
        },
        pressed && { opacity: 0.68 },
      ]}
    >
      <AppText
        style={selected ? { color: theme.colors.tint } : undefined}
        variant="caption"
      >
        {label}
      </AppText>
    </Pressable>
  );
}

function SortRail({
  direction,
  onDirectionToggle,
  onSelect,
  selected,
}: Readonly<{
  direction: 'asc' | 'desc';
  onDirectionToggle(): void;
  onSelect(value: LibrarySort): void;
  selected: LibrarySort;
}>): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();
  const options: readonly (readonly [LibrarySort, string])[] = [
    ['recent_read', t('library.sort.recentRead')],
    ['recent_import', t('library.sort.recentImport')],
    ['title', t('library.sort.title')],
    ['author', t('library.sort.author')],
  ];
  return (
    <View style={[styles.sortRow, { gap: theme.spacing.xs }]}>
      <ScrollView
        accessibilityRole="tablist"
        contentContainerStyle={{ gap: theme.spacing.xs }}
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.flex}
      >
        {options.map(([value, label]) => (
          <FilterChip
            key={value}
            label={label}
            onPress={() => onSelect(value)}
            selected={selected === value}
          />
        ))}
      </ScrollView>
      <Pressable
        accessibilityLabel={
          direction === 'asc'
            ? t('library.sort.ascending')
            : t('library.sort.descending')
        }
        accessibilityRole="button"
        onPress={onDirectionToggle}
        style={({ pressed }) => [
          styles.directionButton,
          {
            backgroundColor: theme.colors.card,
            borderColor: theme.colors.border,
            borderRadius: theme.radius.control,
            height: theme.control.minimumTouchTarget,
            width: theme.control.minimumTouchTarget,
          },
          pressed && { backgroundColor: theme.colors.tintMuted },
        ]}
      >
        <AppIcon
          color={theme.colors.tint}
          decorative
          name="sort"
          size={theme.control.iconMedium}
        />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  directionButton: {
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    justifyContent: 'center',
  },
  filterChip: {
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    justifyContent: 'center',
  },
  flex: {
    flex: 1,
  },
  sortRow: {
    alignItems: 'center',
    flexDirection: 'row',
  },
  viewToolbar: {
    alignItems: 'center',
    flexDirection: 'row',
  },
});
