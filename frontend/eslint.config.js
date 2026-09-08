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
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    plugins: { react },
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      // Core no-unused-vars cannot see identifiers that are only referenced from
      // JSX, so without this rule every `import { motion }` used as <motion.div>
      // is reported as dead and "cleaning it up" breaks the render.
      'react/jsx-uses-vars': 'error',
      'react/jsx-uses-react': 'error',

      // React Compiler rules from eslint-plugin-react-hooks v7. Each of these
      // flags a genuine pattern worth revisiting (a ref written during render,
      // a mount flag set in an effect, Math.random() in a decorative
      // background), but every fix is a real refactor rather than a cleanup.
      // Kept visible as warnings so they are tracked, not silenced; CI fails on
      // errors only.
      'react-hooks/purity': 'warn',
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/refs': 'warn',

      'no-unused-vars': [
        'error',
        {
          varsIgnorePattern: '^[A-Z_]',
          argsIgnorePattern: '^_',
          // `({ node, ...props })` deliberately drops a prop before spreading
          // the rest; that is the idiom react-markdown expects, not dead code.
          ignoreRestSiblings: true,
          // `catch (err) {}` where the error is intentionally swallowed.
          caughtErrors: 'none',
          args: 'after-used',
        },
      ],
    },
  },
])
