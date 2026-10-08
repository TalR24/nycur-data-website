export const meta = {
  name: 'nys-extract-session',
  description: 'Answer one NYS session\'s signed-law packets on Max with Sonnet subagents (one per chunk)',
  phases: [{ title: 'Answer', detail: 'one Sonnet subagent per chunk of packets' }],
}
const RESULT = {
  type: 'object',
  properties: {
    answered: { type: 'integer' },
    skipped: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, reason: { type: 'string' } }, required: ['name', 'reason'] } },
  },
  required: ['answered', 'skipped'],
}
const RULES = `You answer New York STATE law packets: extract the duties and powers each law gives State and local government.
For each packet path in the list file, read the packet fully and follow every RULE in it, especially:
- only State and local government duty-holders, never private parties; the actor is always the government body that holds the duty or power (never a passive sentence's subject); name a local government's specific locality when the law names one;
- in an amended section only NEW matter inside {{ }} creates a record; never extract from [bracketed] deleted text; text reprinted unchanged is never a record;
- extensions of an existing authority (new sunset date, amount, place, class, or a deletion that widens it) ARE records with extends_existing true;
- on_effective_date only for one-time setup duties with no stated deadline; triggered or precondition duties get none; a cutoff date is not a deadline;
- no records for early-rulemaking boilerplate, cap or residency exemptions, Local Finance Law useful-life entries, goals or findings, appropriation amounts, or conditions ("subject to", "unless") of another record;
- quotes copied character for character from the law as it reads after amendment (deleted text left out), 10-60 words; one record per distinct duty or power.
Write ONLY the JSON object the packet's ANSWER FORMAT footer asks for, to the exact results path it names (the results/ folder beside the packet). Check each file parses (python3 -m json.tool) and each quote appears in the packet text with [deleted] spans and {{ }} markers stripped. If a law is too long or unclear to do carefully, skip it. Do not edit any other file.
Return the count answered and each skipped packet with its reason.`
phase('Answer')
const results = await pipeline(args.chunks, (chunk, _o, i) =>
  agent(`${RULES}\n\nYour list file: ${chunk}`, { label: `${args.session} chunk ${i}`, phase: 'Answer', model: 'sonnet', schema: RESULT }))
const ok = results.filter(Boolean)
const answered = ok.reduce((s, r) => s + r.answered, 0)
const skipped = ok.flatMap(r => r.skipped)
log(`${args.session}: ${answered} answered, ${skipped.length} skipped, ${results.length - ok.length} chunks failed`)
return { session: args.session, answered, skipped, failed_chunks: results.map((r, i) => r ? null : args.chunks[i]).filter(Boolean) }