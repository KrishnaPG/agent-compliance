---
tags: [trigger, no-trigger]
model: sonnet
max_turns: 2
allowed_tools: [Skill]
---
Explain what this function does:

```python
def expired(keys, now, days=30):
    return [k for k in keys if (now - k.created).days > days]
```
