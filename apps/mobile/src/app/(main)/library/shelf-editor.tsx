import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState, type ReactNode } from 'react';
import { View } from 'react-native';

import { useLibrary, type ShelfSummary } from '../../../features/library/public';
import { useI18n } from '../../../shared/i18n/public';
import {
  AppButton,
  AppTextField,
  InlineNotice,
  LoadingState,
  notifyOperationSucceeded,
  notifyOperationWarning,
  ScreenScaffold,
  useAppTheme,
} from '../../../shared/ui/public';

export default function ShelfEditorRoute(): ReactNode {
  const { shelfId } = useLocalSearchParams<{ shelfId?: string }>();
  const router = useRouter();
  const library = useLibrary();
  const theme = useAppTheme();
  const { t } = useI18n();
  const shelf = findShelf(library.state.shelves, shelfId);
  const [draft, setDraft] = useState({ dirty: false, value: '' });
  const [failure, setFailure] = useState(false);
  const editing = shelfId !== undefined;
  const name = draft.dirty ? draft.value : shelf?.name ?? '';
  const normalizedName = name.trim();
  const busy =
    library.state.shelves.phase === 'ready' &&
    library.state.shelves.mutatingShelfId !== null;

  const submit = (): void => {
    if (
      normalizedName.length === 0 ||
      busy ||
      (editing && shelf === undefined)
    ) {
      return;
    }
    setFailure(false);
    const operation =
      editing && shelf !== undefined
        ? library.renameShelf(shelf.id, normalizedName)
        : library.createShelf(normalizedName);
    void operation.then((outcome) => {
      if (outcome.outcome === 'succeeded') {
        void notifyOperationSucceeded();
        router.back();
      } else {
        void notifyOperationWarning();
        setFailure(true);
      }
    });
  };

  return (
    <>
      <Stack.Screen
        options={{
          title: editing
            ? t('library.shelves.editTitle')
            : t('library.shelves.modalTitle'),
        }}
      />
      <ScreenScaffold contentStyle={{ gap: theme.spacing.lg }} edges={[]}>
        {editing &&
        (library.state.shelves.phase === 'idle' ||
          library.state.shelves.phase === 'loading') ? (
          <LoadingState label={t('library.shelves.loading')} />
        ) : editing && shelf === undefined ? (
          <View style={{ gap: theme.spacing.md }}>
            <InlineNotice
              body={t('library.shelves.notFoundBody')}
              title={t('library.shelves.notFoundTitle')}
              tone="danger"
            />
            <AppButton
              label={t('common.retry')}
              onPress={() => {
                void library.loadShelves();
              }}
              variant="secondary"
            />
          </View>
        ) : null}
        {failure ? (
          <InlineNotice
            body={t('library.issue.shelfMutation')}
            title={t('library.issue.title')}
            tone="danger"
          />
        ) : null}
        <AppTextField
          autoCapitalize="sentences"
          autoCorrect
          disabled={busy || (editing && shelf === undefined)}
          error={
            name.length > 0 && normalizedName.length === 0
              ? t('library.shelves.nameRequired')
              : undefined
          }
          label={t('library.shelves.nameLabel')}
          maxLength={100}
          onChangeText={(value) => setDraft({ dirty: true, value })}
          onSubmitEditing={submit}
          placeholder={t('library.shelves.namePlaceholder')}
          returnKeyType="done"
          value={name}
        />
        <View style={{ gap: theme.spacing.sm }}>
          <AppButton
            disabled={
              normalizedName.length === 0 ||
              busy ||
              (editing && shelf === undefined)
            }
            label={
              editing
                ? t('library.shelves.renameAction')
                : t('library.shelves.createAction')
            }
            loading={busy}
            onPress={submit}
          />
          {editing ? null : (
            <AppButton
              iconName="upload"
              label={t('library.import.action')}
              onPress={() => router.replace('/library/import')}
              variant="ghost"
            />
          )}
        </View>
      </ScreenScaffold>
    </>
  );
}

function findShelf(
  state: ReturnType<typeof useLibrary>['state']['shelves'],
  shelfId: string | undefined,
): ShelfSummary | undefined {
  if (shelfId === undefined || state.phase !== 'ready') return undefined;
  return state.data.shelves.find((shelf) => shelf.id === shelfId);
}
