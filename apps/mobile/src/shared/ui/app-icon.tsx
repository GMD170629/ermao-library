import { SymbolView, type AndroidSymbol, type SFSymbol } from 'expo-symbols';
import type { ReactNode } from 'react';
import { type ColorValue } from 'react-native';

import { useAppTheme } from './theme-provider';

export type AppIconName =
  | 'back'
  | 'book-closed'
  | 'camera'
  | 'check'
  | 'chevron-right'
  | 'close'
  | 'edit'
  | 'eye'
  | 'eye-off'
  | 'filter'
  | 'globe'
  | 'grid'
  | 'home'
  | 'info'
  | 'keyboard'
  | 'library'
  | 'link'
  | 'list'
  | 'lock'
  | 'logout'
  | 'mail'
  | 'more'
  | 'person'
  | 'play'
  | 'plus'
  | 'qr'
  | 'reader'
  | 'refresh'
  | 'scan'
  | 'search'
  | 'server'
  | 'settings'
  | 'sort'
  | 'sun'
  | 'trash'
  | 'upload'
  | 'warning';

type PlatformSymbol = Readonly<{
  android: AndroidSymbol;
  ios: SFSymbol;
  web: AndroidSymbol;
}>;

const symbols = {
  back: symbol('chevron.backward', 'arrow_back'),
  'book-closed': symbol('book.closed', 'book_2'),
  camera: symbol('camera', 'photo_camera'),
  check: symbol('checkmark', 'check'),
  'chevron-right': symbol('chevron.forward', 'chevron_right'),
  close: symbol('xmark', 'close'),
  edit: symbol('pencil', 'edit'),
  eye: symbol('eye', 'visibility'),
  'eye-off': symbol('eye.slash', 'visibility_off'),
  filter: symbol('line.3.horizontal.decrease', 'filter_list'),
  globe: symbol('globe', 'public'),
  grid: symbol('square.grid.2x2', 'grid_view'),
  home: symbol('house', 'home'),
  info: symbol('info.circle', 'info'),
  keyboard: symbol('keyboard', 'keyboard'),
  library: symbol('books.vertical', 'local_library'),
  link: symbol('link', 'link'),
  list: symbol('list.bullet', 'view_list'),
  lock: symbol('lock', 'lock'),
  logout: symbol('rectangle.portrait.and.arrow.right', 'logout'),
  mail: symbol('envelope', 'mail'),
  more: symbol('ellipsis', 'more_horiz'),
  person: symbol('person.crop.circle', 'account_circle'),
  play: symbol('play.circle.fill', 'play_circle'),
  plus: symbol('plus', 'add'),
  qr: symbol('qrcode', 'qr_code_scanner'),
  reader: symbol('book', 'menu_book'),
  refresh: symbol('arrow.clockwise', 'refresh'),
  scan: symbol('viewfinder', 'document_scanner'),
  search: symbol('magnifyingglass', 'search'),
  server: symbol('server.rack', 'dns'),
  settings: symbol('gearshape', 'settings'),
  sort: symbol('arrow.up.arrow.down', 'sort'),
  sun: symbol('sun.max', 'light_mode'),
  trash: symbol('trash', 'delete'),
  upload: symbol('square.and.arrow.up', 'upload_file'),
  warning: symbol('exclamationmark.triangle', 'warning'),
} satisfies Readonly<Record<AppIconName, PlatformSymbol>>;

export type AppIconProps = Readonly<{
  accessibilityLabel?: string;
  color?: ColorValue;
  decorative?: boolean;
  name: AppIconName;
  size?: number;
  testID?: string;
}>;

export function AppIcon({
  accessibilityLabel,
  color,
  decorative = true,
  name,
  size,
  testID,
}: AppIconProps): ReactNode {
  const theme = useAppTheme();
  const resolvedSize = size ?? theme.control.iconLarge;

  return (
    <SymbolView
      {...(decorative
        ? {
            accessibilityElementsHidden: true,
            importantForAccessibility: 'no-hide-descendants' as const,
          }
        : {
            accessibilityLabel,
            accessibilityRole: 'image' as const,
            accessible: true,
          })}
      name={symbols[name]}
      size={resolvedSize}
      testID={testID}
      tintColor={color ?? theme.colors.text}
      type="monochrome"
      weight="regular"
    />
  );
}

function symbol(ios: SFSymbol, android: AndroidSymbol): PlatformSymbol {
  return { android, ios, web: android };
}
