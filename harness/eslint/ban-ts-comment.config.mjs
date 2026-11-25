// The measurer's own eslint config: one rule, so the count of ban-ts-comment findings does not
// depend on what a project's config enables. Copied next to the checkout's node_modules to run.
import tseslint from "typescript-eslint";

export default [
  {
    files: ["**/*.ts", "**/*.tsx", "**/*.mts", "**/*.cts"],
    languageOptions: { parser: tseslint.parser },
    plugins: { "@typescript-eslint": tseslint.plugin },
    rules: { "@typescript-eslint/ban-ts-comment": "error" },
  },
];
