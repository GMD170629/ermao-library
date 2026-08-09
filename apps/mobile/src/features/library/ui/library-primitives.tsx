import type { ReactNode } from 'react';
import {
  Image,
  Pressable,
  StyleSheet,
  TextInput,
  View,
  useWindowDimensions,
  type ImageSourcePropType,
} from 'react-native';

import {
  AppIcon,
  AppText,
  useAppTheme,
} from '../../../shared/ui/public';
import type {
  LibraryBook,
  LibraryView,
} from '../model/library';

export type LibraryCoverSource = ImageSourcePropType | undefined;

export type BookCoverProps = Readonly<{
  accessibilityLabel: string;
  size: 'large' | 'medium' | 'small';
  source?: LibraryCoverSource;
}>;

export function BookCover({
  accessibilityLabel,
  size,
  source,
}: BookCoverProps): ReactNode {
  const theme = useAppTheme();
  const width =
    size === 'large'
      ? theme.spacing.xxxl * 2 + theme.spacing.lg
      : size === 'medium'
        ? theme.spacing.xxxl * 2
        : theme.control.regularHeight;

  return (
    <View
      accessibilityLabel={accessibilityLabel}
      accessibilityRole="image"
      style={[
        styles.cover,
        theme.elevation.card,
        {
          aspectRatio: 5 / 7,
          backgroundColor: theme.colors.tintMuted,
          borderColor: theme.colors.border,
          borderRadius: theme.radius.compact,
          width,
        },
      ]}
    >
      {source === undefined ? (
        <AppIcon
          color={theme.colors.tint}
          decorative
          name="book-closed"
          size={theme.control.iconLarge}
        />
      ) : (
        <Image
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
          resizeMode="cover"
          source={source}
          style={styles.coverImage}
        />
      )}
    </View>
  );
}

export type LibrarySearchButtonProps = Readonly<{
  accessibilityHint: string;
  label: string;
  onPress(): void;
}>;

export function LibrarySearchButton({
  accessibilityHint,
  label,
  onPress,
}: LibrarySearchButtonProps): ReactNode {
  const theme = useAppTheme();
  return (
    <Pressable
      accessibilityHint={accessibilityHint}
      accessibilityLabel={label}
      accessibilityRole="search"
      hitSlop={4}
      onPress={onPress}
      style={({ pressed }) => [
        styles.search,
        {
          backgroundColor: theme.colors.cardStrong,
          borderColor: theme.colors.borderStrong,
          borderRadius: theme.radius.control,
          gap: theme.spacing.sm,
          minHeight: theme.control.regularHeight,
          paddingHorizontal: theme.spacing.md,
        },
        pressed && { backgroundColor: theme.colors.tintMuted },
      ]}
    >
      <AppIcon
        color={theme.colors.textMuted}
        decorative
        name="search"
        size={theme.control.iconMedium}
      />
      <AppText muted numberOfLines={1} style={styles.flex}>
        {label}
      </AppText>
    </Pressable>
  );
}

export type LibrarySearchFieldProps = Readonly<{
  accessibilityLabel: string;
  clearAccessibilityLabel: string;
  onChangeText(value: string): void;
  onSubmit(): void;
  placeholder: string;
  value: string;
}>;

export function LibrarySearchField({
  accessibilityLabel,
  clearAccessibilityLabel,
  onChangeText,
  onSubmit,
  placeholder,
  value,
}: LibrarySearchFieldProps): ReactNode {
  const theme = useAppTheme();
  return (
    <View
      style={[
        styles.search,
        {
          backgroundColor: theme.colors.cardStrong,
          borderColor: theme.colors.borderStrong,
          borderRadius: theme.radius.control,
          gap: theme.spacing.sm,
          minHeight: theme.control.regularHeight,
          paddingHorizontal: theme.spacing.md,
        },
      ]}
    >
      <AppIcon
        color={theme.colors.textMuted}
        decorative
        name="search"
        size={theme.control.iconMedium}
      />
      <TextInput
        accessibilityLabel={accessibilityLabel}
        allowFontScaling
        autoCapitalize="none"
        autoCorrect={false}
        enterKeyHint="search"
        maxLength={200}
        onChangeText={onChangeText}
        onSubmitEditing={onSubmit}
        placeholder={placeholder}
        placeholderTextColor={theme.colors.textMuted}
        returnKeyType="search"
        style={[
          styles.searchInput,
          theme.type.body,
          { color: theme.colors.text },
        ]}
        value={value}
      />
      {value.length === 0 ? null : (
        <Pressable
          accessibilityLabel={clearAccessibilityLabel}
          accessibilityRole="button"
          hitSlop={8}
          onPress={() => onChangeText('')}
          style={styles.clearSearch}
        >
          <AppIcon
            color={theme.colors.textMuted}
            decorative
            name="close"
            size={theme.control.iconSmall}
          />
        </Pressable>
      )}
    </View>
  );
}

export type ViewSwitcherProps = Readonly<{
  gridLabel: string;
  listLabel: string;
  onChange(view: LibraryView): void;
  value: LibraryView;
}>;

export function ViewSwitcher({
  gridLabel,
  listLabel,
  onChange,
  value,
}: ViewSwitcherProps): ReactNode {
  const theme = useAppTheme();
  return (
    <View
      accessibilityRole="tablist"
      style={[
        styles.switcher,
        {
          backgroundColor: theme.colors.card,
          borderColor: theme.colors.border,
          borderRadius: theme.radius.control,
          padding: theme.spacing.xxs,
        },
      ]}
    >
      {([
        ['grid', gridLabel],
        ['list', listLabel],
      ] as const).map(([candidate, label]) => {
        const selected = candidate === value;
        return (
          <Pressable
            accessibilityLabel={label}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            hitSlop={4}
            key={candidate}
            onPress={() => onChange(candidate)}
            style={({ pressed }) => [
              styles.switcherItem,
              {
                backgroundColor: selected
                  ? theme.colors.tintMuted
                  : 'transparent',
                borderRadius: theme.radius.compact,
                height: theme.control.minimumTouchTarget,
                width: theme.control.minimumTouchTarget,
              },
              pressed && { opacity: 0.68 },
            ]}
          >
            <AppIcon
              color={
                selected ? theme.colors.tint : theme.colors.textMuted
              }
              decorative
              name={candidate}
              size={theme.control.iconMedium}
            />
          </Pressable>
        );
      })}
    </View>
  );
}

export type BookCollectionProps = Readonly<{
  books: readonly LibraryBook[];
  coverAccessibilityLabel(book: LibraryBook): string;
  coverSource?(book: LibraryBook): LibraryCoverSource;
  emptyLabel: string;
  view: LibraryView;
}>;

export function BookCollection({
  books,
  coverAccessibilityLabel,
  coverSource,
  emptyLabel,
  view,
}: BookCollectionProps): ReactNode {
  const theme = useAppTheme();
  const { fontScale, width } = useWindowDimensions();
  if (books.length === 0) {
    return (
      <AppText muted style={{ paddingVertical: theme.spacing.xl }}>
        {emptyLabel}
      </AppText>
    );
  }
  if (view === 'list') {
    return (
      <View style={{ gap: theme.spacing.xs }}>
        {books.map((book) => (
          <BookListItem
            book={book}
            coverAccessibilityLabel={coverAccessibilityLabel(book)}
            key={book.id}
            {...(coverSource === undefined
              ? {}
              : { coverSource: coverSource(book) })}
          />
        ))}
      </View>
    );
  }

  const horizontalPadding =
    width >= theme.breakpoint.expandedMinWidth
      ? theme.breakpoint.expandedHorizontalPadding
      : width < 360
        ? theme.breakpoint.compactMinimumHorizontalPadding
        : theme.breakpoint.compactHorizontalPadding;
  const contentWidth = Math.min(
    width - horizontalPadding * 2,
    theme.breakpoint.contentMaxWidth,
  );
  const columns =
    fontScale >= 1.6 ? 2 : width >= theme.breakpoint.expandedMinWidth ? 4 : 3;
  const itemWidth =
    (contentWidth - theme.spacing.md * (columns - 1)) / columns;

  return (
    <View style={[styles.bookGrid, { gap: theme.spacing.md }]}>
      {books.map((book) => (
        <BookGridItem
          book={book}
          coverAccessibilityLabel={coverAccessibilityLabel(book)}
          itemWidth={itemWidth}
          key={book.id}
          {...(coverSource === undefined
            ? {}
            : { coverSource: coverSource(book) })}
        />
      ))}
    </View>
  );
}

type BookItemProps = Readonly<{
  book: LibraryBook;
  coverAccessibilityLabel: string;
  coverSource?: LibraryCoverSource;
}>;

function BookListItem({
  book,
  coverAccessibilityLabel,
  coverSource,
}: BookItemProps): ReactNode {
  const theme = useAppTheme();
  return (
    <View
      accessibilityLabel={`${book.title}, ${book.author}`}
      accessible
      style={[
        styles.bookListItem,
        {
          borderBottomColor: theme.colors.border,
          gap: theme.spacing.md,
          minHeight: theme.control.minimumTouchTarget,
          paddingVertical: theme.spacing.sm,
        },
      ]}
    >
      <BookCover
        accessibilityLabel={coverAccessibilityLabel}
        size="small"
        {...(coverSource === undefined ? {} : { source: coverSource })}
      />
      <View style={[styles.flex, { gap: theme.spacing.xxs }]}>
        <AppText numberOfLines={2} variant="label">
          {book.title}
        </AppText>
        <AppText muted numberOfLines={1} variant="caption">
          {book.author}
        </AppText>
      </View>
    </View>
  );
}

function BookGridItem({
  book,
  coverSource,
  itemWidth,
}: BookItemProps & Readonly<{ itemWidth: number }>): ReactNode {
  const theme = useAppTheme();
  return (
    <View
      accessibilityLabel={`${book.title}, ${book.author}`}
      accessible
      style={[
        { gap: theme.spacing.xs, width: itemWidth },
      ]}
    >
      <View style={styles.gridCoverFrame}>
        <View
          style={[
            styles.gridCover,
            {
              backgroundColor: theme.colors.tintMuted,
              borderColor: theme.colors.border,
              borderRadius: theme.radius.compact,
            },
          ]}
        >
          {coverSource === undefined ? (
            <AppIcon
              color={theme.colors.tint}
              decorative
              name="book-closed"
              size={theme.control.iconLarge}
            />
          ) : (
            <Image
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
              resizeMode="cover"
              source={coverSource}
              style={styles.coverImage}
            />
          )}
        </View>
      </View>
      <AppText numberOfLines={2} variant="label">
        {book.title}
      </AppText>
      <AppText muted numberOfLines={1} variant="caption">
        {book.author}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  bookGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  bookListItem: {
    alignItems: 'center',
    borderBottomWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
  },
  clearSearch: {
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 44,
    minWidth: 44,
  },
  cover: {
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    justifyContent: 'center',
    overflow: 'hidden',
  },
  coverImage: {
    height: '100%',
    width: '100%',
  },
  flex: {
    flex: 1,
  },
  gridCover: {
    alignItems: 'center',
    aspectRatio: 5 / 7,
    borderWidth: StyleSheet.hairlineWidth,
    justifyContent: 'center',
    overflow: 'hidden',
    width: '100%',
  },
  gridCoverFrame: {
    width: '100%',
  },
  search: {
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
  },
  searchInput: {
    flex: 1,
    minHeight: 44,
    paddingVertical: 0,
  },
  switcher: {
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
  },
  switcherItem: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
