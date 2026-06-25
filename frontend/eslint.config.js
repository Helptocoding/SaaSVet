import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    plugins: { react },
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    settings: { react: { version: 'detect' } },
    rules: {
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }],
      // Mark identifiers used only inside JSX (e.g. <motion.div>, <Component/>)
      // as used, so no-unused-vars stops false-flagging valid JSX references.
      // Only react/* rule enabled on purpose — not the full recommended set,
      // to avoid introducing a wave of new rules.
      'react/jsx-uses-vars': 'error',
    },
  },
  // Archivos de configuración (contexto Node, no browser) — exponer globals de
  // Node (process, etc.) para que no-undef no marque vite.config.js / este archivo.
  {
    files: ['vite.config.js', 'eslint.config.js'],
    languageOptions: { globals: globals.node },
  },
])
