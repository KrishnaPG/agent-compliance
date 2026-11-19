export const meta = {
  name: 'harness-build',
  description: 'Brick harness: build the ready items in parallel, each in its own worktree and environment slot, on branch bh/<item>; a retry gets its previous commit and the numbers it missed',
  whenToUse: 'When the state lists ready items (dependencies met, own targets not met, not blocked). Args: path to .brick-harness/config.json, or {configPath, dryRun, items}.',
  phases: [{ title: 'Build', detail: 'one builder per ready item, worktree isolation, capped by config.concurrency' }],
}

const NEED = ['config', 'files', 'problems', 'decision']
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

phase('Build')
const readyAll = state.ready.concat(state.ready_system) // system items: wiring code and end-to-end tests
const wanted = A.items || readyAll
const notReady = wanted.filter(id => readyAll.indexOf(id) < 0)
if (notReady.length) log('skipped (dependencies not met, blocked, or already met): ' + notReady.join(', '))
const todo = wanted.filter(id => readyAll.indexOf(id) >= 0)
if (!todo.length) return { refs: [], failed: [], dryRun: DRY }
function feedback(id) { // a rebuilt item gets its previous commit and the numbers it missed, nothing else
  const b = state.bricks.find(x => x.id === id), l = b && b.last
  if (!l) return ''
  const unmet = (l.unmet || []).map(u => u.metric + ': actual ' + (u.actual == null ? 'not measured' : u.actual) + ', required ' + u.op + ' ' + u.value).join('; ')
  return '\nThis is a retry. Previous attempt: commit ' + l.ref + ' (measurer status ' + l.status + ').' +
    (/^[0-9a-f]{40}$/.test(l.ref) ? ' Start from it: after the reset, run `git merge --no-edit ' + l.ref + '` and resolve any conflict.' : '') +
    '\nUnmet targets, actual vs required: ' + (unmet || 'none listed') + '\nMeasurer errors: ' + JSON.stringify(l.errors || [])
}
function commands(id, slot) { // rendered by bh-state (overrides, {item}, {out}, ...); the slot is filled here
  const c = state.commands[id] || {}, s = state.config.slots || {}
  const port = String((s.port_base || 20000) + slot * (s.port_stride || 100))
  const fill = t => t.split('{slot}').join(String(slot)).split('{port_base}').join(port)
  return ['env_setup', 'test', 'bench'].filter(k => c[k]).map(k => {
    const v = typeof c[k] === 'string' ? { run: c[k] } : c[k]
    return '\n  ' + k + ': ' + (v.pending ? 'pending (' + v.pending + '); the measurer cannot score it yet' : fill(v.run))
  }).join('')
}
const briefCmd = id => cmdOf('brief', 'bh-brief --config ' + CONFIG) + ' ' + id
const bStatus = id => (state.bricks.find(x => x.id === id) || {}).status
const REMEASURE = ['unmeasured', 'stale', 'conflict', 'met-uncommitted'] // no current measurement: code may already be met
const preHead = todo.filter(id => REMEASURE.indexOf(bStatus(id)) >= 0) // score it at HEAD before spending a builder
if (DRY) return { dryRun: true, would_commit_plan: state.uncommitted, would_measure_head_first: preHead,
  would_build: todo.map(id => ({ item: id, retry_of: ((state.bricks.find(x => x.id === id) || {}).last || {}).ref || null, feedback: feedback(id), brief: briefCmd(id), commands: commands(id, 0) })) }
if (state.uncommitted.length) { // builders fork from HEAD, so the plan must be in HEAD
  const c = await commitPlan('plan before build')
  if (!ok(c)) return { refs: [], failed: todo, error: 'could not commit plan files: ' + c.error }
  const fresh = await loadState(['decision'])
  if (!fresh) return { refs: [], failed: todo, error: 'state reload failed: ' + stateFail }
  const d = fresh.decision
  if (d.uncommitted.length) return { refs: [], failed: todo, error: 'plan files still uncommitted: ' + JSON.stringify(d.uncommitted) }
  state.decision = d; fromDecision(state)
}
// Measure at HEAD, before any builder, every unmeasured ready item: the deterministic measurer decides whether code that
// already exists is met. Only items that come back unmet are built (with the measurer's numbers as feedback).
const measuredHead = preHead.length ? (await measureAll(preHead.map(id => ({ item: id, ref: 'HEAD' })))) : []
if (measuredHead.length) {
  const c = await commitPlan('scoreboard') // the scoreboard is the measurer's; commit it so builders fork from it
  if (!ok(c)) log('scoreboard commit failed before build: ' + c.error)
  const fresh = await loadState(['decision'])
  if (!fresh) return { refs: [], failed: [], measuredHead, error: 'state reload failed after measuring at HEAD: ' + stateFail }
  const d = fresh.decision
  state.decision = d; fromDecision(state)
}
const stillReady = state.ready.concat(state.ready_system)
const metAtHead = measuredHead.filter(m => m.status === 'met' || m.status === 'met-uncommitted').map(m => m.item) // only unmet (or not measurable) get a builder
if (metAtHead.length) log('met at HEAD, no builder spawned: ' + metAtHead.join(', '))
const toBuild = todo.filter(id => metAtHead.indexOf(id) < 0 && stillReady.indexOf(id) >= 0) // unmet at HEAD (or not measurable) are built
if (!toBuild.length) return { refs: [], failed: [], measuredHead, attempted: todo }
const built = await pool(toBuild, (id, k, slot) => agent(
  'Load the skill agent-compliance:harness and follow its section "Build". You are a phase agent of a running harness workflow: follow only that section; start no workflow.\nItem: ' + id +
  '\nYour first command, from the project root: `' + briefCmd(id) + '`. It prints your work packet: the job, contract, targets, commands, the cited spec passages, the contracts of the items you depend on, your owned paths, the stack pins and the rules. ' +
  'The packet and your owned paths are all you need: do not read other documents. Anything you need that it does not hold, return in missing_context (one line each); do not look it up elsewhere.' +
  '\nCatalogue (you may add helper entries): ' + file('catalogue') +
  '\nStart: in your worktree run `git reset --hard ' + state.head + '` (a fresh worktree has nothing to lose); that commit holds the plan (' + state.plan_head + ').' +
  feedback(id) +
  '\nEnvironment slot ' + slot + '. Commands for this item, run from the project root (set up the slot first):' + commands(id, slot) +
  '\nProtected paths (the measurer fails a commit that changes any of them): ' + JSON.stringify(state.config.protected || []) + '\n' + RULES +
  '\nDo not edit the targets, the item list, the contracts, the config or the scoreboard, and do not run the measurer. ' +
  'When done: commit and return the full commit sha. Do not create or move any branch: the harness points bh/' + id + ' at your commit. You do not decide whether the item passes; the measurer does.',
  { label: id, phase: 'Build', isolation: 'worktree', schema: { type: 'object', required: ['item', 'ref', 'catalogue_added'], properties: {
    item: STR, ref: { type: 'string', pattern: '^[0-9a-f]{40}$' }, catalogue_added: STRS, notes: STR, missing_context: STRS } }, ...tier('build') }))
// A builder in an isolated worktree cannot move branches: bh-branch (deterministic, from the main checkout) points bh/<item>
// at the commit it returned, after checking the plan commit, plan paths and protected paths.
const BRANCH_SCHEMA = { type: 'object', required: ['ok'], properties: { ok: { type: 'boolean' }, item: STR, branch: STR, ref: STR, previous: { type: ['string', 'null'] }, error: STR } }
const set = await pool(toBuild, async (id, k) => {
  const r = built[k] && built[k].ref
  if (!r) return null
  if (r === state.head || r === state.plan_head) return { ok: true, nochange: true, ref: 'HEAD' } // no new commit: no change; the item is measured at HEAD
  return agent(VERBATIM + cmdOf('branch', 'bh-branch --config ' + CONFIG) + ' --item ' + id + ' --ref ' + r, { label: 'branch ' + id, effort: 'low', schema: BRANCH_SCHEMA })
})
// What a builder could not find in its packet is returned as missing_context; the run files it as a finding (harness-run.js)
const missing = []
toBuild.forEach((id, k) => ((built[k] && built[k].missing_context) || []).forEach(m => missing.push({ summary: 'missing context for ' + id + ': ' + m, kind: 'missing-context', source: 'build', impact: [id] })))
const refs = [], failed = [], nochange = []
toBuild.forEach((id, k) => {
  const s = set[k]
  if (!built[k] || !s || !s.ok) {
    failed.push(id)
    if (built[k]) log(id + ': branch bh/' + id + ' not set: ' + (s ? s.error : 'branch agent failed'))
    return
  }
  if (s.nochange) { nochange.push(id); log(id + ': builder made no change; measuring it at HEAD') }
  refs.push({ ref: s.ref, items: [id] })
})
return { refs, failed, nochange, measuredHead, attempted: todo, built: built.filter(Boolean), missing_context: missing }
