import { useEffect, useRef, type ReactNode } from 'react';

import { ImportScreen, useLibrary } from '../../../features/library/public';

export default function LibraryImportRoute(): ReactNode {
  const {
    cancelImport,
    chooseAndImport,
    loadImportTargets,
    state,
  } = useLibrary();
  const importState = useRef(state.import);

  useEffect(() => {
    importState.current = state.import;
  }, [state.import]);

  useEffect(() => {
    void loadImportTargets();
    return () => {
      if (
        importState.current.phase === 'ready' &&
        importState.current.upload.phase === 'uploading'
      ) {
        cancelImport();
      }
    };
  }, [cancelImport, loadImportTargets]);

  return (
    <ImportScreen
      onCancel={cancelImport}
      onChooseFiles={(targetPath) => {
        void chooseAndImport(targetPath);
      }}
      onLoadTargets={() => {
        void loadImportTargets();
      }}
      state={state.import}
    />
  );
}
