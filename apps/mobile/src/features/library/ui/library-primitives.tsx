import type { ReactNode } from 'react';
import {
  Image,
  StyleSheet,
  TextInput,
  View,
  useWindowDimensions,
  type ImageSourcePropType,
} from 'react-native';

import {
  AppButton,
  AppIcon,
  AppText,
  ContentPressable,
  SystemListItem,
  SystemSegmentedControl,
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
      ? theme.spacing.xxxl * 2 + theme.spacing.xs
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
    <ContentPressable
      accessibilityHint={accessibilityHint}
      accessibilityLabel={label}
      accessibilityRole="search"
      onPress={onPress}
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
      <AppText muted numberOfLines={1} style={styles.flex}>
        {label}
      </AppText>
    </ContentPressable>
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
        <AppButton
          containerStyle={styles.clearSearch}
          label={clearAccessibilityLabel}
          onPress={() => onChangeText('')}
          variant="ghost"
        />
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
  return (
    <SystemSegmentedControl
      onChange={onChange}
      options={[
        { label: gridLabel, value: 'grid' },
        { label: listLabel, value: 'list' },
      ]}
      testID="library-view-switcher"
      value={value}
    />
  );
}

export type BookCollectionProps = Readonly<{
  books: readonly LibraryBook[];
  coverAccessibilityLabel(book: LibraryBook): string;
  coverSource?(book: LibraryBook): LibraryCoverSource;
  emptyLabel: string;
  titleLineLimit?: 1 | 2;
  view: LibraryView;
}>;

export function BookCollection({
  books,
  coverAccessibilityLabel,
  coverSource,
  emptyLabel,
  titleLineLimit = 2,
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
            titleLineLimit={titleLineLimit}
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
          titleLineLimit={titleLineLimit}
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
  titleLineLimit: 1 | 2;
}>;

function BookListItem({
  book,
  coverAccessibilityLabel,
  coverSource,
}: BookItemProps): ReactNode {
  return (
    <SystemListItem
      label={book.title}
      leading={
        <BookCover
          accessibilityLabel={coverAccessibilityLabel}
          size="small"
          {...(coverSource === undefined ? {} : { source: coverSource })}
        />
      }
      supportingText={book.author}
      testID={`library-book-${book.id}`}
    />
  );
}

function BookGridItem({
  book,
  coverSource,
  itemWidth,
  titleLineLimit,
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
      <AppText numberOfLines={titleLineLimit} variant="label">
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
});
