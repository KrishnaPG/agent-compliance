import tseslint from "typescript-eslint";

export default [
  ...tseslint.configs.recommended,
  { rules: { "@typescript-eslint/ban-ts-comment": "error" } },
];
