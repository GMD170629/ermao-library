const mockReact = require('react');
const mockReactNative = require('react-native');

function mockTextContent(node) {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(mockTextContent).join('');
  if (mockReact.isValidElement(node)) return mockTextContent(node.props.children);
  return '';
}

jest.mock('@expo/ui', () => {
  const element = mockReact.createElement;
  const { Pressable, Text, View } = mockReactNative;
  return {
    Button: ({ children, disabled = false, onPress, style, testID, variant }) =>
      element(
        Pressable,
        {
          accessibilityLabel: mockTextContent(children),
          accessibilityRole: 'button',
          accessibilityState: { disabled },
          disabled,
          onPress,
          style,
          testID: testID ?? `native-button-${variant}`,
        },
        children,
      ),
    Host: ({ children }) => element(View, null, children),
    Icon: ({ accessibilityLabel }) =>
      element(View, {
        accessibilityElementsHidden: accessibilityLabel === undefined,
        accessibilityLabel,
      }),
    ListItem: ({
      children,
      leading,
      onPress,
      supportingText,
      testID,
      trailing,
    }) =>
      element(
        Pressable,
        {
          accessibilityLabel: mockTextContent(children),
          accessibilityRole: onPress === undefined ? 'text' : 'button',
          disabled: onPress === undefined,
          onPress,
          testID,
        },
        leading,
        element(Text, null, children),
        supportingText === undefined
          ? null
          : element(Text, null, supportingText),
        trailing,
      ),
    RNHostView: ({ children }) => element(View, null, children),
    Row: ({ children }) => element(View, null, children),
    Text: ({ children }) => element(Text, null, children),
  };
});

jest.mock('@expo/ui/community/menu', () => {
  const element = mockReact.createElement;
  const { Pressable, Text, View } = mockReactNative;
  return {
    MenuView: ({ actions, children, onPressAction, testID }) =>
      element(
        View,
        { testID },
        children,
        ...actions.map((action) =>
          element(
            Pressable,
            {
              accessibilityRole: 'menuitem',
              accessibilityState: {
                disabled: action.attributes?.disabled === true,
                selected: action.state === 'on',
              },
              disabled: action.attributes?.disabled === true,
              key: action.id,
              onPress: () =>
                onPressAction({ nativeEvent: { event: action.id } }),
            },
            element(Text, null, action.title),
          ),
        ),
      ),
  };
});

jest.mock('@expo/ui/community/segmented-control', () => {
  const element = mockReact.createElement;
  const { Pressable, Text, View } = mockReactNative;
  return {
    __esModule: true,
    default: ({ onChange, selectedIndex, values }) =>
      element(
        View,
        { accessibilityRole: 'tablist' },
        ...values.map((option, index) =>
          element(
            Pressable,
            {
              accessibilityRole: 'tab',
              accessibilityState: { selected: selectedIndex === index },
              key: option,
              onPress: () =>
                onChange({ nativeEvent: { selectedSegmentIndex: index } }),
            },
            element(Text, null, option),
          ),
        ),
      ),
  };
});

jest.mock('expo-haptics', () => ({
  NotificationFeedbackType: { Success: 'success', Warning: 'warning' },
  notificationAsync: jest.fn().mockResolvedValue(undefined),
  selectionAsync: jest.fn().mockResolvedValue(undefined),
}));
