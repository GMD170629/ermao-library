module.exports = {
  preset: 'jest-expo',
  testMatch: [
    '<rootDir>/src/**/*.native.test.tsx',
    '<rootDir>/tests/ui/**/*.test.tsx',
  ],
  setupFilesAfterEnv: ['<rootDir>/tests/ui/setup-native-ui.cjs'],
  transformIgnorePatterns: [
    'node_modules/(?!(.pnpm|(jest-)?react-native|@react-native(-community)?|expo(nent)?|@expo(nent)?/.*|@expo-google-fonts/.*|expo-router|standard-navigation|react-navigation|@react-navigation/.*))',
  ],
};
