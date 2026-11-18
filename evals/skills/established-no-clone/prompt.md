---
tags: [skills]
model: sonnet
max_turns: 30
timeout_seconds: 900
allowed_tools: [Skill, Read, Glob, Grep, Bash, WebFetch]
---
The project is the directory /home/ubuntu/workspace/agent-compliance/evals/skills/established-no-clone/proj. Nothing in it may be written; put the result in your reply.

scripts/copy-changes.sh copies changed rows between two PostgreSQL 16 databases by polling a timestamp column every minute. Should we replace it with PostgreSQL 16's built-in logical replication (publication and subscription)? There is no bindings file and no overlay.
