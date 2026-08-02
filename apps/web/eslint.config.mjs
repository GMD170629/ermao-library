import { defineConfig, globalIgnores } from 'eslint/config';
import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';

/**
 * React Hooks 7 enables React Compiler diagnostics in its recommended preset.
 * They were not part of this project's previous Next.js 14 lint contract and
 * require a separate behavior-preserving React architecture refactor. Keep the
 * established rules-of-hooks and exhaustive-deps gates during this migration.
 * Owner: Web platform.
 * Removal condition: complete the standalone behavior-preserving React Compiler
 * migration and clear every deferred-rule diagnostic.
 */
const deferredReactCompilerRules = {
  'react-hooks/config': 'off',
  'react-hooks/error-boundaries': 'off',
  'react-hooks/gating': 'off',
  'react-hooks/globals': 'off',
  'react-hooks/immutability': 'off',
  'react-hooks/incompatible-library': 'off',
  'react-hooks/preserve-manual-memoization': 'off',
  'react-hooks/purity': 'off',
  'react-hooks/refs': 'off',
  'react-hooks/set-state-in-effect': 'off',
  'react-hooks/set-state-in-render': 'off',
  'react-hooks/static-components': 'off',
  'react-hooks/unsupported-syntax': 'off',
  'react-hooks/use-memo': 'off'
};

export default defineConfig([
  ...nextCoreWebVitals,
  {
    rules: deferredReactCompilerRules
  },
  globalIgnores([
    '.next/**',
    '.next-*/**',
    'out/**',
    'build/**',
    'generated/**',
    'next-env.d.ts'
  ])
]);
