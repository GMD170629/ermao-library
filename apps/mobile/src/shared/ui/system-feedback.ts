import * as Haptics from 'expo-haptics';

export async function notifySelectionChanged(): Promise<void> {
  await Haptics.selectionAsync();
}

export async function notifyOperationSucceeded(): Promise<void> {
  await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
}

export async function notifyOperationWarning(): Promise<void> {
  await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
}
