import { useState, type ReactNode } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { useI18n } from '../../../shared/i18n/public';
import {
  AppButton,
  AppIcon,
  AppText,
  InlineNotice,
  LoadingState,
  PageHeader,
  ScreenScaffold,
  SurfaceCard,
  useAppTheme,
} from '../../../shared/ui/public';
import type { ImportState, ImportTarget } from '../model/library';

export type ImportScreenProps = Readonly<{
  onBack(): void;
  onCancel(): void;
  onChooseFiles(targetPath: string): void;
  onLoadTargets(): void;
  state: ImportState;
}>;

export function ImportScreen({
  onBack,
  onCancel,
  onChooseFiles,
  onLoadTargets,
  state,
}: ImportScreenProps): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();

  return (
    <ScreenScaffold
      contentStyle={{ gap: theme.spacing.xl }}
      edges={[]}
      testID="library-import-screen"
    >
      <PageHeader
        backAccessibilityHint={t('library.import.backHint')}
        backLabel={t('common.back')}
        description={t('library.import.subtitle')}
        onBack={onBack}
        title={t('library.import.title')}
      />

      {state.phase === 'idle' || state.phase === 'loading-targets' ? (
        <LoadingState label={t('library.import.loadingTargets')} />
      ) : state.phase === 'failure' ? (
        <View style={{ gap: theme.spacing.md }}>
          <InlineNotice
            body={
              state.failure.reason === 'forbidden'
                ? t('library.import.forbidden')
                : t('library.issue.loadBody')
            }
            title={t('library.issue.title')}
            tone="danger"
          />
          {state.failure.reason === 'forbidden' ? null : (
            <AppButton
              label={t('common.retry')}
              onPress={onLoadTargets}
              variant="secondary"
            />
          )}
        </View>
      ) : (
        <ImportReadyContent
          onCancel={onCancel}
          onChooseFiles={onChooseFiles}
          state={state}
        />
      )}
    </ScreenScaffold>
  );
}

function ImportReadyContent({
  onCancel,
  onChooseFiles,
  state,
}: Readonly<{
  onCancel(): void;
  onChooseFiles(targetPath: string): void;
  state: Extract<ImportState, Readonly<{ phase: 'ready' }>>;
}>): ReactNode {
  const theme = useAppTheme();
  const { formatNumber, t } = useI18n();
  const [selectedTargetPath, setSelectedTargetPath] = useState<string | null>(
    () => getInitialTargetPath(state),
  );
  return (
    <View style={{ gap: theme.spacing.xl }}>
          <View style={{ gap: theme.spacing.sm }}>
            <AppText accessibilityRole="header" variant="headline">
              {t('library.import.targetTitle')}
            </AppText>
            <AppText muted>{t('library.import.targetBody')}</AppText>
            {state.targets.targets.length === 0 ? (
              <InlineNotice
                body={t('library.import.noTargets')}
                title={t('library.import.noTargetsTitle')}
                tone="warning"
              />
            ) : (
              <View style={{ gap: theme.spacing.xs }}>
                {state.targets.targets.map((target) => (
                  <ImportTargetRow
                    key={target.folderId}
                    onPress={() => setSelectedTargetPath(target.rootPath)}
                    selected={
                      selectedTargetPath === target.rootPath ||
                      selectedTargetPath?.startsWith(`${target.rootPath}/`) ===
                        true
                    }
                    target={target}
                  />
                ))}
              </View>
            )}
          </View>

          {state.upload.phase === 'failed' ? (
            <InlineNotice
              body={
                state.upload.failure.code === 'UNSUPPORTED_FILE_EXTENSION'
                  ? t('library.import.unsupportedFile')
                  : t('library.import.failure')
              }
              title={t('library.import.failureTitle')}
              tone="danger"
            />
          ) : state.upload.phase === 'succeeded' ? (
            <SurfaceCard accessibilityLiveRegion="polite" padding="compact">
              <View style={[styles.successHeader, { gap: theme.spacing.sm }]}>
                <AppIcon
                  color={theme.colors.success}
                  decorative
                  name="check"
                  size={theme.control.iconLarge}
                />
                <AppText variant="headline">
                  {t('library.import.successTitle')}
                </AppText>
              </View>
              <AppText>
                {t('library.import.successBody', {
                  count: formatNumber(state.upload.result.saved),
                })}
              </AppText>
              {state.upload.result.files.map((file) => (
                <AppText key={file.sourcePath} muted variant="caption">
                  {file.name}
                </AppText>
              ))}
            </SurfaceCard>
          ) : null}

          {state.upload.phase === 'uploading' ? (
            <View style={{ gap: theme.spacing.md }}>
              <View
                accessibilityLabel={t('library.import.progress', {
                  completed: formatNumber(state.upload.completedFiles),
                  total: formatNumber(state.upload.totalFiles),
                })}
                accessibilityRole="progressbar"
                accessibilityValue={{
                  max: state.upload.totalFiles,
                  min: 0,
                  now: state.upload.completedFiles,
                }}
                style={[
                  styles.progressTrack,
                  {
                    backgroundColor: theme.colors.border,
                    borderRadius: theme.radius.compact,
                    height: theme.spacing.xs,
                  },
                ]}
              >
                <View
                  style={[
                    styles.progressFill,
                    {
                      backgroundColor: theme.colors.tint,
                      borderRadius: theme.radius.compact,
                      width: `${
                        state.upload.totalFiles === 0
                          ? 0
                          : (state.upload.completedFiles /
                              state.upload.totalFiles) *
                            100
                      }%`,
                    },
                  ]}
                />
              </View>
              <AppText muted>
                {t('library.import.progress', {
                  completed: formatNumber(state.upload.completedFiles),
                  total: formatNumber(state.upload.totalFiles),
                })}
              </AppText>
              <AppButton
                label={t('common.cancel')}
                onPress={onCancel}
                variant="secondary"
              />
            </View>
          ) : (
            <AppButton
              disabled={selectedTargetPath === null}
              fullWidth
              label={
                state.upload.phase === 'failed'
                  ? t('library.import.retryAction')
                  : t('library.import.chooseAction')
              }
              leadingIcon={
                <AppIcon
                  color={theme.colors.onAction}
                  decorative
                  name="upload"
                  size={theme.control.iconMedium}
                />
              }
              onPress={() => {
                if (selectedTargetPath !== null) {
                  onChooseFiles(selectedTargetPath);
                }
              }}
            />
          )}
          <AppText muted variant="caption">
            {t('library.import.supportedFormats')}
          </AppText>
    </View>
  );
}

function getInitialTargetPath(
  state: Extract<ImportState, Readonly<{ phase: 'ready' }>>,
): string | null {
  const preferredPath = state.targets.selectedTargetPath;
  const selected = state.targets.targets.find(
    (target) =>
      target.enabled &&
      preferredPath !== null &&
      (preferredPath === target.rootPath ||
        preferredPath.startsWith(`${target.rootPath}/`)),
  );
  const fallback = state.targets.targets.find((target) => target.enabled);
  return selected === undefined ? fallback?.rootPath ?? null : preferredPath;
}

function ImportTargetRow({
  onPress,
  selected,
  target,
}: Readonly<{
  onPress(): void;
  selected: boolean;
  target: ImportTarget;
}>): ReactNode {
  const theme = useAppTheme();
  const { t } = useI18n();
  return (
    <Pressable
      accessibilityHint={
        target.enabled ? t('library.import.targetHint') : undefined
      }
      accessibilityLabel={target.name}
      accessibilityRole="radio"
      accessibilityState={{ checked: selected, disabled: !target.enabled }}
      disabled={!target.enabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.targetRow,
        {
          backgroundColor: selected
            ? theme.colors.tintMuted
            : theme.colors.card,
          borderColor: selected
            ? theme.colors.tint
            : theme.colors.border,
          borderRadius: theme.radius.control,
          gap: theme.spacing.md,
          minHeight: theme.control.regularHeight,
          opacity: target.enabled ? 1 : 0.48,
          padding: theme.spacing.md,
        },
        pressed && { opacity: 0.68 },
      ]}
    >
      <View
        style={[
          styles.radio,
          {
            borderColor: selected
              ? theme.colors.tint
              : theme.colors.borderStrong,
          },
        ]}
      >
        {selected ? (
          <View
            style={[
              styles.radioSelected,
              { backgroundColor: theme.colors.tint },
            ]}
          />
        ) : null}
      </View>
      <View style={[styles.flex, { gap: theme.spacing.xxs }]}>
        <AppText variant="label">{target.name}</AppText>
        <AppText muted numberOfLines={2} variant="caption">
          {target.rootPath}
        </AppText>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
  },
  progressFill: {
    height: '100%',
  },
  progressTrack: {
    overflow: 'hidden',
  },
  radio: {
    alignItems: 'center',
    borderRadius: 10,
    borderWidth: 2,
    height: 20,
    justifyContent: 'center',
    width: 20,
  },
  radioSelected: {
    borderRadius: 5,
    height: 10,
    width: 10,
  },
  successHeader: {
    alignItems: 'center',
    flexDirection: 'row',
  },
  targetRow: {
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
  },
});
