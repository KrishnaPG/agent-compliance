---
name: vet-oss
description: Collect a third-party package's public supply-chain facts before naming it. Load before suggesting, comparing or adopting a library, tool or image. Not for upgrading or using one already adopted.
---

# Vet an OSS candidate

Run, per candidate, from any directory (no config, no account):

```
bh vet <system> <package> [<version>]     # system: pypi, npm, go, maven, cargo, nuget
```

It asks three public services and prints one fact per line, then the result JSON, whose `api_results[*]` holds each service's answer unchanged:

- **deps.dev**: licenses, publish date, advisory count, source repository.
- **OpenSSF Scorecard**: the source repository's published score and each check's score.
- **OSV**: known vulnerabilities of that version.

Compare the candidates on these facts, plus what the project needs from the tool (each need as `path:line` of the code it replaces). Quote the facts; add no grade of your own. A service error is a fact: say which one and why. A candidate with no package (a container image, a SaaS) has no facts here: say so and cite its maintained security page.
