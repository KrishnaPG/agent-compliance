# Agent jobs pack, PR rules

Pack `agent-jobs` for base catalog 1.4.0. Scope: designs in which a program or harness starts AI agent jobs (an LLM with tools, run by the program without a person in the conversation): no agent in a mechanical path, minimal context, agent definitions, stable prompt prefix, caps and convergence, structured results, owner questions. Loaded only when the project overlay names this pack. Each row is the whole rule.

| ID | Rule | Provenance | Test question |
|---|---|---|---|
| AJ-07 | Questions that agent jobs raise for the project owner (only those PR-10 makes the owner's) are collected into one list per run and put to the owner once, at the end of the run or when no work can continue around them; no job waits for an answer (RL-16). Each answer is recorded with its question where the project records decisions, every job looks the record up before it asks, and a question whose recorded answer still holds (its cited inputs unchanged) is never asked again. NA where no agent job can raise a question for the project owner. | Convention: owner questions batched per run, recorded and never asked again | Where are a run's owner questions collected and their answers recorded, what does a job read before it asks, and which question in the records was asked twice? |
