import { Icon, type IconName } from '@expo/ui';
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

export type AppPlatformSymbol = Readonly<{
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
} satisfies Readonly<Record<AppIconName, AppPlatformSymbol>>;

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

export function appIconSymbol(name: AppIconName): AppPlatformSymbol {
  return symbols[name];
}

export function appNativeIconName(name: AppIconName): IconName {
  const platformSymbol = symbols[name];
  switch (name) {
    case 'back':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/arrow_back.xml') });
    case 'book-closed':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/book_2.xml') });
    case 'camera':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/photo_camera.xml') });
    case 'check':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/check.xml') });
    case 'chevron-right':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/chevron_right.xml') });
    case 'close':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/close.xml') });
    case 'edit':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/edit.xml') });
    case 'eye':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/visibility.xml') });
    case 'eye-off':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/visibility_off.xml') });
    case 'filter':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/filter_list.xml') });
    case 'globe':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/public.xml') });
    case 'grid':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/grid_view.xml') });
    case 'home':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/home.xml') });
    case 'info':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/info.xml') });
    case 'keyboard':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/keyboard.xml') });
    case 'library':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/local_library.xml') });
    case 'link':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/link.xml') });
    case 'list':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/view_list.xml') });
    case 'lock':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/lock.xml') });
    case 'logout':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/logout.xml') });
    case 'mail':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/mail.xml') });
    case 'more':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/more_horiz.xml') });
    case 'person':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/account_circle.xml') });
    case 'play':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/play_circle.xml') });
    case 'plus':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/add.xml') });
    case 'qr':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/qr_code_scanner.xml') });
    case 'reader':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/menu_book.xml') });
    case 'refresh':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/refresh.xml') });
    case 'scan':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/document_scanner.xml') });
    case 'search':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/search.xml') });
    case 'server':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/dns.xml') });
    case 'settings':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/settings.xml') });
    case 'sort':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/sort.xml') });
    case 'sun':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/light_mode.xml') });
    case 'trash':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/delete.xml') });
    case 'upload':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/upload_file.xml') });
    case 'warning':
      return Icon.select({ ios: platformSymbol.ios, android: import('@expo/material-symbols/warning.xml') });
  }
}

function symbol(ios: SFSymbol, android: AndroidSymbol): AppPlatformSymbol {
  return { android, ios, web: android };
}
