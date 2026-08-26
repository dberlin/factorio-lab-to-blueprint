import tsParser from '@typescript-eslint/parser';
import reactHooks from 'eslint-plugin-react-hooks';

export default [
  {
    // `vendor/**` and `payload/**` are fetched or generated, not written here:
    // emscripten output and a built wheel. Linting them produced sixteen
    // warnings nobody in this repo can act on.
    ignores: ['dist/**', 'payload/**', 'public/**', 'node_modules/**', 'coverage/**', 'vendor/**'],
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: reactHooks.configs['recommended-latest'].rules,
  },
];
