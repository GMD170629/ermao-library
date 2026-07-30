const expoConfig = require('eslint-config-expo/flat');

module.exports = [
  ...expoConfig,
  {
    ignores: ['.expo/**', 'android/**', 'ios/**'],
  },
  {
    files: ['src/**/*.{ts,tsx}', 'index.ts'],
    rules: {
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports' },
      ],
      '@typescript-eslint/no-explicit-any': 'error',
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['**/apps/web/**', '**/features/*/*/private/**'],
              message:
                'Mobile capabilities must use stable public contracts.',
            },
          ],
        },
      ],
    },
  },
];
