---
type: regex
pattern: 'file_path\\?":\s*\\?"([^"\\]*/catalog/[^"\\]+)\\?"[\s\S]*file_path\\?":\s*\\?"\1\\?"'
match: not_contains
target: trace
---
