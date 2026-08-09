import { useEffect, type ReactNode } from 'react';
import { Modal } from 'react-native';

import { ImportScreen } from './import-screen';
import { useLibrary } from './library-provider';

export type LibraryImportModalProps = Readonly<{
  onClose(): void;
  visible: boolean;
}>;

export function LibraryImportModal({
  onClose,
  visible,
}: LibraryImportModalProps): ReactNode {
  const {
    cancelImport,
    chooseAndImport,
    loadImportTargets,
    state,
  } = useLibrary();

  useEffect(() => {
    if (visible) void loadImportTargets();
  }, [loadImportTargets, visible]);

  const close = (): void => {
    if (
      state.import.phase === 'ready' &&
      state.import.upload.phase === 'uploading'
    ) {
      cancelImport();
    }
    onClose();
  };

  return (
    <Modal
      animationType="slide"
      onRequestClose={close}
      presentationStyle="fullScreen"
      visible={visible}
    >
      <ImportScreen
        onBack={close}
        onCancel={cancelImport}
        onChooseFiles={(targetPath) => {
          void chooseAndImport(targetPath);
        }}
        onLoadTargets={() => {
          void loadImportTargets();
        }}
        state={state.import}
      />
    </Modal>
  );
}
