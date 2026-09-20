import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    // NOTE: scoped to JS/JSX — the default espree parser cannot parse
    // TypeScript syntax. TS correctness is enforced by `tsc --noEmit`
    // (`npm run typecheck`, also run as part of `npm run build`).
    // To lint .ts/.tsx as well, add devDependency `typescript-eslint`
    // and set its parser/languageOptions here.
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: { ...globals.browser, process: "readonly" },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // Backend-error propagation pattern: intentional re-throw with new message.
      "preserve-caught-error": "off",
    },
  },
])
