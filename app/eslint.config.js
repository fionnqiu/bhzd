import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    // Generated browser assets and reports are not authored source and must not
    // make local or CI lint results depend on a prior build or test run.
    ignores: ["dist/**", "coverage/**", "playwright-report/**", "test-results/**"],
  },
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}", "tests/**/*.{ts,tsx}", "vite.config.ts"],
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      // Hooks correctness is a runtime concern, whereas dependency suggestions
      // start as warnings so the existing asynchronous flows can be migrated safely.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // The existing codebase has a small, known unused-symbol and CJK-spacing
      // backlog. Keep it visible without blocking the initial correctness gate.
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "no-irregular-whitespace": "warn",
    },
  },
);
