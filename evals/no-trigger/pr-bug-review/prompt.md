---
tags: [trigger, no-trigger]
model: sonnet
max_turns: 2
allowed_tools: [Skill]
---
Review this PR for bugs:

```diff
 def expired(keys, now, days=30):
-    return [k for k in keys if (now - k.created).days > days]
+    return [k for k in keys if (now - k.created).days >= days or k.created is None]
```
