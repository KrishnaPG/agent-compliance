export const meta = {
  name: 'harness-run',
  description: 'Brick harness: one full run (gaps, plan, build+measure rounds, harvest+measure)',
  whenToUse: 'To advance a project by one run; start each run fresh (the work list comes from the project files, not from a resumed run). Args: path to .brick-harness/config.json, or {configPath, dryRun, skip}.',
  phases: [
    { title: 'Gaps', detail: 'report spec gaps; never decide them' },
    { title: 'Plan', detail: "items, targets and contracts from the project's own build order" },
    { title: 'Rounds', detail: 'build ready items, measure, merge what met its targets, re-measure at HEAD' },
    { title: 'Harvest', detail: 'report duplicated helpers; apply only settled picks; measure the change' },
  ],
}

const NEED = ['config', 'files', 'problems', 'decision', 'learning', 'features', 'merged', 'gaps', 'checklist', 'overlay', 'catalogue'] // what this script and the phase workflows it hands state to read
// ---- prelude: identical in every workflow (scripts cannot import); tests check it ----
// args: a config path string, or {configPath, dryRun, state, refs, items, skip, stateCommand, measureCommand, commitCommand, gapsCommand, mergeCommand, branchCommand, loaderModel}.
// Each workflow declares NEED (the state parts it reads, or null for all) before this prelude.
const A = typeof args === 'string' ? { configPath: args } : (args || {})
const CONFIG = A.configPath || '.brick-harness/config.json'
const DRY = !!A.dryRun // dry run: report what would be written and committed; write nothing
const STR = { type: 'string' }, STRS = { type: 'array', items: STR }
const PART_SCHEMA = {
  config: { type: ['object', 'null'] }, config_path: STR, root: STR, problems: STRS, files: { type: 'object' },
  bricks: { type: 'array', items: { type: 'object', required: ['id', 'kind', 'status', 'ready', 'depends_on', 'blocked_by'], properties: {
    id: STR, kind: STR, status: STR, ready: { type: 'boolean' }, depends_on: STRS, blocked_by: STRS,
    last: { type: ['object', 'null'], properties: { ref: STR, status: STR, errors: STRS,
      unmet: { type: 'array', items: { type: 'object', properties: { metric: STR, op: STR, value: { type: 'number' }, actual: { type: ['number', 'null'] } } } } } } } } },
  waves: { type: 'array', items: STRS }, ready: STRS, ready_system: STRS, all_met: { type: 'boolean' }, catalogue: { type: 'object' },
  unmerged: { type: 'array', items: { type: 'object', required: ['item', 'ref'], properties: { item: STR, ref: STR } } },
  uncommitted: STRS, head: { type: ['string', 'null'] }, plan_head: { type: ['string', 'null'] }, branches: { type: 'object' }, commands: { type: 'object' },
  decision: { type: 'object' }, pending: { type: 'object' }, features: { type: 'object' }, merged: { type: 'object' }, checklist: { type: 'array', items: { type: 'object' } }, overlay: { type: ['string', 'null'] }, gaps: { type: 'array', items: { type: 'object' } }, counts: { type: 'object' }, learning: { type: 'object' }, value: { type: 'object' },
}
const ALL_PARTS = Object.keys(PART_SCHEMA)
const PARTS = NEED || ALL_PARTS
const MEASURE_SCHEMA = {
  type: 'object', required: ['ok', 'items'],
  properties: {
    ok: { type: 'boolean' }, error: STR, scoreboard: STR,
    items: { type: 'object', additionalProperties: { type: 'object', required: ['status', 'ref'], properties: {
      status: { enum: ['met', 'unmet', 'met-uncommitted'] }, ref: STR, errors: STRS } } },
  },
}
const GAP_KINDS = ['missing-document', 'dangling-reference', 'no-acceptance', 'no-numeric-target', 'target-without-source', 'target-without-command', 'target-on-unknown-item', 'duplicate-item', 'no-contract', 'missing-dependency', 'item-without-source', 'contradiction', 'untracked-open-item', 'helper-without-library', 'unsettled-area', 'unmet-after-rounds', 'not-derivable', 'missing-context', 'other']
const GAP_ITEM = { type: 'object', required: ['kind', 'summary', 'tag', 'evidence'], properties: {
  kind: { enum: GAP_KINDS }, summary: STR, tag: { enum: ['owner-decides', 'fixable'] }, area: STR, resolve_with: STR,
  severity: { enum: ['S1', 'S2', 'S3', 'S4'] }, proof: { enum: ['reproduced', 'trigger', 'theoretical'] }, impact: STRS, rule: STR, reopens: STR, answered_by: STR, // ranking fields (bh-rank key) and the recorded decision a gap would reopen
  evidence: { type: 'array', items: { type: 'object', required: ['file', 'line'], properties: { file: STR, line: { type: 'integer' }, quote: STR } } },
  looked_in: STRS } }
const VERBATIM = 'Run exactly this one command from the project root and nothing else; do not edit any file; ' +
  'a non-zero exit code is a normal result. If it may outlast your shell\'s time limit, start it as a background task and wait for its completion ' +
  'notification; never sleep or poll. Return the JSON object it printed on stdout, verbatim, as the structured output:\n'
// canon/checksum reproduce lib/bhcore.py canon/checksum exactly: a part shortened or altered in transit fails its checksum
function canon(v) {
  if (v === null || v === undefined) return 'n'
  if (v === true) return 't'
  if (v === false) return 'f'
  if (typeof v === 'number') return 'd' + (Math.abs(v) < 1e15 ? String(Math.floor(v)) : 'big')
  if (typeof v === 'string') return 's' + v.length + ':' + v
  if (Array.isArray(v)) return '[' + v.map(canon).join('') + ']'
  return '{' + Object.keys(v).filter(k => v[k] !== null && v[k] !== undefined).sort().map(k => canon(k) + canon(v[k])).join('') + '}'
}
function checksum(v) {
  const s = canon(v)
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0 }
  return ('0000000' + h.toString(16)).slice(-8)
}
let state = A.state && PARTS.every(p => p in A.state) ? A.state : null
function cmdOf(key, dflt) { const c = state && state.config && state.config.commands; return A[key + 'Command'] || (c && c[key]) || dflt }
function tier(phase) {
  const o = {}, c = (state && state.config) || {}
  if (c.models && c.models[phase]) o.model = c.models[phase]
  if (c.efforts && c.efforts[phase]) o.effort = c.efforts[phase]
  return o
}
function ok(r) { return !!r && !r.error }
function fromDecision(s) { // the workflows read the capped decision part, never every item: the first page of items not met, in build order
  const d = s && s.decision
  if (!d || !d.pending) return s
  for (const k of ['head', 'plan_head', 'all_met', 'ready', 'ready_system', 'unmerged', 'uncommitted', 'branches', 'commands']) s[k] = d[k]
  s.bricks = d.pending.map(p => Object.assign({}, p, { last: (d.last || {})[p.id] || null }))
  return s
}
async function readState(parts, sliced) { // sliced: a re-read of parts that failed their checksum, one slice at a time
  const c = (state && state.config) || {}
  const o = { label: 'state', effort: (c.efforts && c.efforts.loader) || 'low', schema: { type: 'object', required: ['checksums'].concat(parts),
    properties: Object.assign({ checksums: { type: 'object' } }, ...parts.map(p => ({ [p]: PART_SCHEMA[p] }))) } }
  const model = A.loaderModel || (c.models && c.models.loader)
  if (model) o.model = model
  const cmd = cmdOf('state', 'bh-state --config ' + CONFIG)
  const how = sliced
    ? 'Your earlier copy of these parts did not match. Read each one only in slices, never whole: run `' + cmd + ' --value <key> | cut -c1-2000`, then `cut -c2001-4000`, and so on through the first empty slice, and join the slices in order without changing a character. ' +
      '`--value <key>` prints only that key\'s bare JSON value, so the joined text is that key\'s value: return it as the key\'s value, with no wrapper object around it. '
    : 'Then run `' + cmd + ' --part <key>` once for each of these keys: ' + parts.join(', ') + ' (each prints {"<key>": value}; return the value inside, not the wrapper). ' +
      'If any output looks cut, shortened or summarised, run `' + cmd + ' --value <key>` (the bare value) piped through `cut -c1-3000` and the next slices (`cut -c3001-6000` ...) and join them. '
  return agent('Read the harness state in parts, so no output is shortened by your tools. Do not edit any file; ' +
    'a non-zero exit code is a normal result. First run `' + cmd + ' --parts`: it prints {"parts": [...], "checksums": {...}}. ' +
    how + (sliced ? 'The keys are: ' + parts.join(', ') + '. ' : '') + 'Return one object: "checksums" from the first command and each key\'s value, all verbatim, ' +
    'as the structured output. If the first command prints "config": null, the config cannot be read: return nothing.', o)
}
function unwrap(s, parts) { // a part returned as {<part>: value} (the --part wrapper) is accepted as value when value passes the checksum
  if (!s || !s.checksums) return s
  for (const p of parts) {
    const v = s[p]
    if (v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length === 1 && p in v && s.checksums[p] !== checksum(v) && s.checksums[p] === checksum(v[p])) s[p] = v[p]
  }
  return s
}
function badParts(s, parts) { unwrap(s, parts); return s ? parts.filter(p => !(p in s) || !s.checksums || s.checksums[p] !== checksum(s[p])) : parts }
let stateFail = '' // which parts failed their checksum when loadState gave up
async function loadState(parts) { // up to 3 re-reads of the parts that fail their checksum, each in slices; then give up
  parts = parts || PARTS
  let s = await readState(parts, false)
  let bad = badParts(s, parts)
  for (let n = 1; bad.length && n <= 3; n++) {
    log('state parts failed their checksum: ' + bad.join(', ') + '; re-read ' + n + ' of 3, in slices')
    const r = await readState(bad, true)
    const still = badParts(r, bad)
    s = s || { checksums: {} }
    s.checksums = Object.assign({}, s.checksums)
    for (const p of bad) if (r && still.indexOf(p) < 0) { s[p] = r[p]; s.checksums[p] = r.checksums[p] }
    bad = badParts(s, parts)
  }
  if (bad.length) { stateFail = 'part(s) ' + bad.join(', ') + ' failed their checksum after 3 re-reads'; log('state unavailable: ' + stateFail + '; run `bh-state --config ' + CONFIG + '` to see why'); return null }
  return fromDecision(s)
}
async function commitPlan(name) { // deterministic: commits only the harness-owned files; a dry run commits nothing
  const cmd = cmdOf('commit', 'bh-commit --config ' + CONFIG) + (DRY ? ' --dry-run' : ' --message "brick-harness: ' + name + '"')
  const r = await agent(VERBATIM + cmd, { label: DRY ? 'would commit' : 'commit plan', effort: 'low', schema: { type: 'object', required: ['committed'], properties: {
    committed: { type: 'boolean' }, dry_run: { type: 'boolean' }, files: STRS, head: STR, error: STR } } })
  if (!ok(r)) log('plan commit failed (' + name + '): ' + (r ? r.error : 'agent failed'))
  return r || { committed: false, error: 'commit agent failed' }
}
async function writeGaps(found, source, unmet) { // deterministic merge; rejects findings whose file:line does not resolve
  found = found || []
  const cmd = cmdOf('gaps', 'bh-gaps --config ' + CONFIG) + ' --source ' + source + (unmet && unmet.length ? ' --unmet ' + unmet.join(' ') : '') +
    (source === 'cycle' ? ' --brief' : '') + ' --add -' + (DRY ? '' : ' --write') + " <<'BH_GAPS_EOF'\n" + JSON.stringify(found) + '\nBH_GAPS_EOF'
  const r = await agent(VERBATIM + cmd, { label: 'gaps ' + source, effort: 'low', schema: { type: 'object', required: ['received', 'accepted'], properties: {
    gaps: { type: 'array' }, gaps_total: { type: 'integer' }, counts: { type: 'object' }, received: { type: 'integer' }, accepted: { type: 'integer' }, rejected: { type: 'array' }, written: STRS, error: STR,
    learning: { type: 'object' }, value: { type: 'object' }, stuck: { type: 'array', items: { type: 'object' } }, stuck_more: { type: 'integer' } } } })
  if (!r) return { error: 'gaps agent failed' }
  // the tool derives one gap per item not met for source cycle, so it may receive more than was sent
  if (!r.error && (r.received < found.length || (source !== 'cycle' && r.received > found.length + (unmet || []).length) || r.accepted + (r.rejected || []).length !== r.received))
    return { ...r, error: 'gap count mismatch: sent ' + found.length + ' (+' + (unmet || []).length + ' unmet), received ' + r.received + ', accepted ' + r.accepted + ', rejected ' + (r.rejected || []).length }
  if ((r.rejected || []).length) log(source + ': ' + r.rejected.length + ' finding(s) rejected (evidence did not resolve)')
  return r
}
async function runMeasurer(item, ref, slot) { // one item per call, so each call stays within an agent's shell limit
  const cmd = cmdOf('measure', 'bh-measure --config ' + CONFIG) + ' --item ' + item + '@' + ref + ' --slot ' + slot
  return agent(VERBATIM + cmd, { schema: MEASURE_SCHEMA, label: 'measure ' + item, ...tier('measure') })
}
async function measureAll(pairs) { // pairs: [{item, ref}]; returns [{item, ref, status, errors}]
  const runs = await pool(pairs, (p, k, slot) => runMeasurer(p.item, p.ref, slot))
  return pairs.map((p, k) => { const r = runs[k], it = r && r.items && r.items[p.item]
    return { item: p.item, ref: p.ref, status: it ? it.status : 'not measured', errors: it ? (it.errors || []) : [r ? (r.error || 'no result') : 'measurer agent failed'] } })
}
async function pool(items, fn) { // concurrency cap from config; slot = worker index, unique among running workers
  const cap = Math.max(1, Math.min(16, ((state && state.config) || {}).concurrency || 2))
  const out = new Array(items.length)
  let next = 0
  async function worker(slot) {
    for (let k = next++; k < items.length; k = next++) { try { out[k] = await fn(items[k], k, slot) } catch (e) { log('failed: ' + JSON.stringify(items[k]) + ': ' + e); out[k] = null } }
  }
  await Promise.all(Array.from({ length: Math.min(cap, items.length) }, (_, s) => worker(s)))
  return out
}
function rawPath(key) { const f = state.files && state.files[key]; return f ? f.rel : '(not configured)' }
function file(key) {
  const f = state.files && state.files[key]
  if (!f) return '(not configured)'
  return f.rel + (f.section ? ' (section "' + f.section + '")' : '') + (f.exists ? '' : f.create ? ' (missing; you may create it)' : ' (missing; do not create)')
}
function catSkill(name) { return 'agent-compliance:' + name } // a skill of this plugin, referenced by name, never copied
function standardsRef() { const s = state.config.standards; return 'Standards (read only): ' + file('standards') + (s ? '; rule catalog ' + JSON.stringify(s) : '') }
if (!state) state = await loadState()
if (state) fromDecision(state)
if (!state || !state.config) return { error: 'harness state unavailable; run `bh-state --config ' + CONFIG + '` to see why' }
if (state.problems.length) log('state problems: ' + state.problems.join(' | '))
const RULES = 'Rules: paths are relative to the project root (of your own worktree, if you have one; then write nothing outside it); never write the scoreboard (only the measurer does) or the gap report (only bh-gaps does); ' +
  'never write the project\'s own documents (features, standards, decision records, stack manifest, build order, status): the owner decides architecture and standards, the harness only reports gaps in them; ' +
  'create a file only when it is marked "you may create it"; OSS before code: follow ' + catSkill('vet-oss') + '; ' +
  'to wait for anything, wait on the task\'s completion, never sleep or poll; keep records short.' +
  (DRY ? '\nDRY RUN: write no file and commit nothing; describe in your answer what you would write.' : '')
// ---- end prelude ----

// SG-15: the tracker is reconciled with the measured status (the only close and reopen), then admission takes entries within the horizon.
const TRACKER_SCHEMA = { type: 'object', properties: { tracker: { type: ['string', 'null'] }, closed: STRS, reopened: STRS, mismatches: { type: 'array', items: { type: 'object' } },
  room: { type: 'integer' }, admit: { type: 'array', items: { type: 'object' } }, admitted: STRS, not_admitted: { type: 'integer' }, stalled: { type: ['object', 'null'] },
  claimed_elsewhere: { type: 'array', items: { type: 'object' } }, claim_held: { type: 'array', items: { type: 'object' } }, unreachable: { type: ['string', 'null'] },
  facts: { type: 'array', items: { type: 'object' } }, error: STR } }
async function trackerTool(tool, label) { // deterministic; a failure is reported, never a gate
  const r = await agent(VERBATIM + cmdOf(tool.slice(3), tool + ' --config ' + CONFIG) + (DRY ? '' : ' --write'), { label, effort: 'low', schema: TRACKER_SCHEMA })
  if (!ok(r)) log(label + ' failed: ' + (r ? r.error : 'agent failed'))
  return r || { error: label + ' agent failed' }
}

// workflow() nests one level only, so the phase workflows never call workflow() themselves.
async function sub(name, extra) {
  const a = { configPath: CONFIG, dryRun: DRY, stateCommand: A.stateCommand, measureCommand: A.measureCommand, commitCommand: A.commitCommand,
    gapsCommand: A.gapsCommand, rankCommand: A.rankCommand, mergeCommand: A.mergeCommand, branchCommand: A.branchCommand, loaderModel: A.loaderModel, state, ...extra }
  try { return await workflow('agent-compliance:' + name, a) } catch (e) {
    if (!/unknown|not found|no such|does not exist/i.test(String(e))) throw e // only a name lookup falls back to the bare name
    return await workflow(name, a)
  }
}
// A round reloads only `decision` (small and capped at limits.decision_items, so it is copied back exactly) and derives from it the first page
// of items not met, their commands and last results; the big parts (files, config, gaps) are read in full only after the gaps and plan phases, which can change them.
async function refresh(parts) {
  const s = await loadState(parts)
  if (!s) return null
  for (const p of parts) state[p] = s[p]
  return fromDecision(state)
}
const report = { dryRun: DRY, gaps: null, plan: null, rounds: [], harvest: null, stuck: [], stuck_more: 0, learning: null, value: null, stopped: null }
// Budget (config budgets): a limit, never a verdict. Tokens this run has spent are counted from here; the run may spend run_tokens and
// never more than the workflow budget has left. Before each round it ends when what is left is below one round's reserve.
const BUD = state.config.budgets || {}
const spent0 = typeof budget !== 'undefined' ? budget.spent() : 0
function tokensLeft() { // null: no limit applies
  const l = []
  if (typeof budget === 'undefined') return null
  if (BUD.run_tokens) l.push(BUD.run_tokens - (budget.spent() - spent0))
  const r = budget.remaining()
  if (typeof r === 'number' && isFinite(r)) l.push(r)
  return l.length ? Math.min(...l) : null
}
const skip = A.skip || []
for (const name of ['gaps', 'plan']) {
  phase(name === 'gaps' ? 'Gaps' : 'Plan')
  if (skip.indexOf(name) >= 0) continue
  report[name] = await sub('harness-' + name)
  state = await loadState()
  if (!state) return { ...report, error: 'state reload failed after ' + name + ': ' + stateFail }
}
phase('Rounds')
const maxRounds = DRY ? 1 : (state.config.max_rounds || 3) // a dry run changes nothing, so one round shows it all
const attempted = new Set(), why = {} // why[item]: how its last attempt ended
let reserve = BUD.round_reserve_tokens || 0 // one round's tokens: the config's, or the largest round so far when higher
const sellableOf = s => ((s.decision && s.decision.value) || {}).sellable_at_head || []
const sellable0 = sellableOf(state) // features sellable before this run's rounds
for (let round = 1; round <= maxRounds; round++) {
  if (!state.ready.length && !state.ready_system.length && !state.unmerged.length) break
  const left = tokensLeft()
  if (left !== null && left < Math.max(reserve, 1)) { report.stopped = 'budget'; log('round ' + round + ': ' + left + ' tokens left, below one round\'s reserve of ' + reserve + '; stopping'); break }
  const roundStart = typeof budget !== 'undefined' ? budget.spent() : 0
  const b = (await sub('harness-build')) || {}
  ;(b.refs || []).forEach(r => r.items.forEach(i => { attempted.add(i); why[i] = 'unmet' }))
  ;(b.attempted || []).forEach(i => attempted.add(i))
  ;(b.nochange || []).forEach(i => { why[i] = 'no-change' })
  ;(b.failed || []).forEach(i => { attempted.add(i); why[i] = 'build-failed' })
  if ((b.missing_context || []).length) { // recorded by bh-rank as findings of kind missing-context (ranked; they feed the owner's learning loop)
    const f = await agent(VERBATIM + cmdOf('rank', 'bh-rank --config ' + CONFIG) + ' --add -' + (DRY ? '' : ' --write') + " <<'BH_FINDINGS_EOF'\n" + JSON.stringify(b.missing_context) + '\nBH_FINDINGS_EOF',
      { label: 'file missing-context', effort: 'low', schema: { type: 'object', properties: { findings: { type: 'array', items: { type: 'object' } }, written: STRS, error: STR } } })
    if (!ok(f)) log('missing-context findings not recorded: ' + (f ? f.error : 'agent failed'))
  }
  const m = (await sub('harness-measure', { refs: b.refs || [] })) || {}
  const merged = m.merged || []
  report.rounds.push({ round, built: b.refs || [], failed: b.failed || [], nochange: b.nochange || [], measured_head_first: b.measuredHead || [], measured: m.measured || [], merged, conflicts: m.conflicts || [],
    remeasured: m.remeasured || [], missing_context: b.missing_context || [], error: b.error || m.error, dry: DRY ? { build: b, measure: m } : undefined })
  if (typeof budget !== 'undefined') reserve = Math.max(reserve, budget.spent() - roundStart)
  if (!(await refresh(['decision']))) return { ...report, error: 'state reload failed in round ' + round + ': ' + stateFail }
  // an unmet item is rebuilt next round with its previous ref and missed numbers; stop when nothing was built or merged
  if (!merged.length && !(b.refs || []).length && !(b.measuredHead || []).length) { log('round ' + round + ': nothing built or merged; stopping'); break }
}
if (!DRY) report.reconcile = await trackerTool('bh-reconcile', 'reconcile tracker') // after the scoreboard commit at HEAD
// SG-19: a feature that became sellable in this run gets one review of its diff by a fresh agent that did not build it (compliance-review scoped to the
// diff's domains); its findings are ranked by bh-rank and become work only as failing tests or targets.
report.reviews = []
for (const f of sellableOf(state).filter(x => sellable0.indexOf(x) < 0)) {
  if (DRY) { report.reviews.push({ feature: f, dry: true }); continue }
  const br = await agent(VERBATIM + cmdOf('brief', 'bh-brief --config ' + CONFIG) + ' --feature ' + f, { label: 'review brief ' + f, effort: 'low',
    schema: { type: 'object', properties: { feature: STR, items: STRS, paths: STRS, base: STR, domains: STRS, packs: STRS, diff: STR, error: STR } } })
  if (!ok(br)) { report.reviews.push({ feature: f, error: br ? br.error : 'brief agent failed' }); continue }
  const rv = await agent('You did not build this feature. Review its diff, read only; write no file. Run `' + br.diff + '` for the diff. ' +
    'Judge it by the method of the skill ' + catSkill('compliance-review') + ', scoped to the catalog domains ' + br.domains.join(', ') + (br.packs.length ? ' and the packs ' + br.packs.join(', ') : '') + ', and the project overlay (' + (state.overlay || 'none configured') + '). ' +
    'Return every rule that does not hold as a finding {summary, rule (the catalog rule id), severity S1..S4, evidence reproduced|trigger|theoretical, where (file:line)}, with source "sellable-review". Report nothing else.',
    { label: 'review ' + f, ...tier('review'), schema: { type: 'object', required: ['findings'], properties: { findings: { type: 'array', items: { type: 'object' } } } } })
  const found = rv && rv.findings || []
  const rec = found.length ? await agent(VERBATIM + cmdOf('rank', 'bh-rank --config ' + CONFIG) + ' --add -' + ' --write' + " <<'BH_FINDINGS_EOF'\n" + JSON.stringify(found) + '\nBH_FINDINGS_EOF',
    { label: 'file review findings ' + f, effort: 'low', schema: { type: 'object', properties: { findings: { type: 'array', items: { type: 'object' } }, written: STRS, error: STR } } }) : null
  report.reviews.push({ feature: f, findings: found.length, recorded: rec ? ok(rec) : null, error: rv ? undefined : 'reviewer failed' })
}
// Every item not met when the rounds end is stuck. The tool derives the list from the files (bh-gaps --source cycle: every other item not met is
// not-attempted, an oscillating target is named); the run passes only what it attempted and how each attempt ended, which is bounded by rounds
// times the ready items of a page. The full list is in gaps.json; the report carries the capped list and `more`.
const leftOver = new Set(state.ready.concat(state.ready_system)) // what a budget stop left unbuilt
const reason = {}
attempted.forEach(i => { reason[i] = why[i] || 'unmet' })
Object.keys(why).forEach(i => { reason[i] = why[i] })
if (report.stopped === 'budget') leftOver.forEach(i => { reason[i] = 'budget' })
// a defect to analyse is reported for the owner, never analysed here; an empty list clears resolved ones (a dry run writes nothing)
const g = await writeGaps([], 'cycle', Object.keys(reason).map(i => i + ':' + reason[i]))
if (ok(g)) {
  report.stuck = g.stuck || []; report.stuck_more = g.stuck_more || 0
  report.learning = g.learning || null; report.value = g.value || null // facts per cycle: owner questions opened, answered, re-asked; value order; never scored
  if (!DRY) await commitPlan('unmet items reported')
} else log('unmet items not reported: ' + g.error)
phase('Harvest')
if (skip.indexOf('harvest') < 0 && (((state.decision.counts || {}).status || {}).met || 0) > 0) {
  await refresh(['decision', 'catalogue', 'merged']) // builders add catalogue entries and items merge; harvest reads them
  const h = (await sub('harness-harvest')) || {}
  const hr = h.refs || []
  report.harvest = { candidates: h.candidates || [], reported: h.reported, error: h.error, measured: hr.length ? await sub('harness-measure', { refs: hr }) : null, dry: DRY ? h : undefined }
  await refresh(['decision'])
  if (!DRY) report.reconcile = await trackerTool('bh-reconcile', 'reconcile tracker after harvest')
}
return { ...report, all_met: state ? state.all_met : false, bricks: state ? state.bricks : [], bricks_more: state && state.decision ? state.decision.more : 0, problems: state ? state.problems : [], gaps_report: state ? rawPath('gaps_md') : null }
