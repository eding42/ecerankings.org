---
name: verify-pdf-affiliations
description: Check PDF-extracted author affiliations against rendered page images using the user's chosen subagent model, with one draft checkpoint per paper and validation before applying results. Use after harvest_ml.py's pdf stage, or whenever PDF affiliations need checking.
---

# Verify PDF affiliations against the page image

> **This skill is the entry point, and the only way image verification runs.**
> - **You** orchestrate, in the session the user is talking to.
> - **The `pdf-affiliation-verifier` subagent** reads images one paper at a time and writes draft answers only inside its assigned `ai_temp/` run directory. It is defined in `.claude/agents/pdf-affiliation-verifier.md`, with Read/Write tools and Haiku by default.
> - **`harvest_ml.py`** only prepares batches and applies results. It never calls a model.
>
> Use the user's selected provider in this session (Claude Code by default).
> Do not introduce API keys or headless `claude -p` processes.

**Why this exists.** The text extractor (`pipeline/pdf_affiliations.py`) misreads some layouts:
- marks printed *before* names ("¹˒³Cong Wei"), which shifts every author by one;
- two affiliations merged into one string.

The final PDF is the version of record, so the page image settles each author's affiliation.

## 1. Prepare (skip if batches already exist)

```bash
python3 pipeline/harvest_ml.py --venue <v> --year <y> --stage verify-prep [--verify-sample 200] [--verify-limit N]
python3 pipeline/harvest_ml.py --venue <v> --year <y> --stage verify-status
```

`verify-prep` writes `pdf-verify/batches/batch-NNNN-<hash>.json`, with about 15 images each, ordered by kind:

| Kind | Which papers | What the image read does |
|---|---|---|
| `review` | The extractor did not fully resolve them. | Becomes their evidence. |
| `conflict` | The PDF and OpenAlex disagree. | Decides between them. |
| `sample` | A fixed sample of high-confidence papers. | Measures extractor accuracy for the gate. |

`verify-status` lists the pending batches with their kinds. A batch is pending when no result file of the same name exists.

New crops render from the source PDF at 300 DPI. Resolution is part of the
image filename and batch identity, so old low-resolution crops/results are not
silently reused. For ambiguous superscripts, make a focused 300 DPI author-block
crop from the original PDF and rerun that paper; enlarging the existing PNG
does not restore glyph detail. The verifier records literal author marks and
the printed institution legend before mapping affiliations. Keep this evidence
in the draft checkpoint for the orchestrator's image spot-check.

## 2. Ask the user. Always, before spawning anything.

Show the `verify-status` totals, then call `AskUserQuestion` with these questions (skip any the user already answered in this conversation):

1. **"Which model should the pdf-affiliation-verifier subagents use?"**
   - **Haiku (Recommended):** the cheapest vision model. In the ICLR 2025 smoke test it matched a person's reading on 13 of 13 authors, including both extractor failure types.
   - **Sonnet:** more careful on dense or blurry blocks; costs more of the subscription.
   - **Opus:** most careful; uses the most.

   State which selected provider/account supplies the usage; do not imply every
   model runs on Claude Code. Small historical smoke tests do not qualify a
   model for dense bylines.
2. **"How much should run now?"**
   - **Pilot (Recommended for a new venue or year):** 2 batches. Spot-check them, then decide.
   - **Review queue only:** the papers whose image read becomes evidence.
   - **Everything pending.**
3. Optionally: **"How many subagents per wave?"** Default 6; offer 3 or 10.

If the user named a different agent type or provider, use that choice and its
available image/file tools. Limit writes to its assigned draft directory and
require the same per-paper JSON schema. Preserve model and scope choices already
authorized in this conversation.

## 3. Fan out

Before scaling a new model, execution mechanism, rendering setting, or layout,
read [run qualification](references/run-qualification.md) and qualify a bounded
pilot. Include dense author blocks, not just an easy control paper. Keep judge
accuracy, file completeness, and the extractor's formal gate distinct.

Choose the execution mechanism using the current session's routing rules:
native provider subagents for eligible same-provider work completed in this turn;
app-managed delegation for background work, another provider, explicit settings,
or when requested. Do not silently switch providers/models or promise native
concurrency beyond available slots. Record the mechanism as well as the model.

Pass each subagent an explicit assignment:
`Batch file: <saved path>. Model: <actual model>. output_dir: <unique directory>.
Scope: <exact paper/author counts>. Read .claude/agents/pdf-affiliation-verifier.md;
read, judge, save, and read back one paper before opening the next.`

If batch continuation fails, preserve the outputs and use one-paper task lists
within the selected mechanism, or run an authorized native/delegated comparison.
Do not repeatedly relaunch the same failing batch with stronger wording or
attribute a normal final response to a platform limit without evidence. A
completed agent turn is not proof of a completed assignment.

One batch per subagent. Create a unique directory for each model/batch/attempt,
under the git-ignored `ai_temp/pdf-affiliation-verification/`. Copy the assigned
batch JSON into that directory with its original filename and pass that saved
task-list path, model, and output directory explicitly to the subagent. The
task list is immutable; the subagent writes only its paper checkpoints. Never
overwrite a previous attempt. Each subagent checkpoints `paper-NNNN.json` after every paper;
it must not preload later images or write outside its assigned directory.
Only the orchestrator writes accepted pipeline result files.

Save `run.json` with `batch` (saved task-list path), `batch_sha256` (its exact
byte hash), `model`, and `mechanism`. The parent can check progress with
`python3 .agents/skills/verify-pdf-affiliations/scripts/check_checkpoints.py <output_dir>`.
This read-only helper validates saved scope and returns the next unfinished task;
it does not judge affiliation accuracy or call a model. A child may also use it
if its available tools support running the command.

Apply this contract to every verifier model/provider, including fallback
subagents. A provider that does not load `.claude/agents/` automatically must
receive that file's instruction body or an explicit instruction to read it.
Make sure image reads and writes in the assigned directory are available;
do not launch with a contradictory read-only prompt. Progress and final counts
come from the saved task list and valid checkpoint files. Unclear author marks
are saved for review and do not stop processing the remaining papers.
Keep the launch prompt focused on the task list, output directory, and next
action: fetch unfinished task, view image, save/read back answers, repeat.
When a progress command is supplied, `work` requires the next tool action and
`done` permits the final summary. Do not offer a voluntary partial-turn exit or
let an estimated turn/token budget count as a blocker; an early exit must name
an observed tool/capability failure. Preserve checkpoints when replacing a run.

## 4. Save each result

Read back the saved drafts rather than relying on the subagent's completion
claim. Each contains `batch`, `model`, an unchanged copy of the batch's `task`,
and its `result`. Check every task appears exactly once, the batch/model/task
match the assignment, and all author names/indexes/order and verdict fields
match the schema. Preserve author slots even when names differ on the page.

Keep incomplete or invalid attempts in `ai_temp/` for inspection; do not promote
them or repair their answers by hand. An explicitly resumed run may reuse only
matching, complete checkpoints. A partial run must report actual saved counts.

After completeness/schema checks and the image spot-check below pass, write
`pdf-verify/results/<same batch file name>` from the draft `result` objects in
batch order:

```json
{"batch": "<batch file name>", "model": "<model used>", "via": "subagent:pdf-affiliation-verifier",
 "results": [ ...the subagent's results array, unchanged... ]}
```

If a saved paper is missing, malformed, or skips an author, leave the batch
without an accepted result file; it stays pending. Draft checkpoints alone do
not count as pipeline verification or satisfy coverage gates.

## 5. Spot-check the judge

Read about 5 images yourself where a subagent disagreed with the extractor,
including dense and symbol-keyed layouts. Check literal marks, their legend
mapping, and the verdict against the parser separately. Count checked papers,
checked author slots, errors and unresolved slots. If errors appear systematic,
hold the affected drafts and adjust resolution/crops or the qualified judge
before scaling; a completed file is not ground truth.

For pilots, report per-author accuracy, per-paper accuracy, and results by
author-count band as described in run qualification. Never present a density-
stratified pilot score as population accuracy or as the formal extractor gate.

## 6. Apply, rebuild, report

```bash
python3 pipeline/harvest_ml.py --venue <v> --year <y> --stage verify-apply   # validates every result file
python3 pipeline/harvest_ml.py --venue <v> --year <y> --stage build
python3 pipeline/harvest_ml.py --venue <v> --year <y> --stage gates
```

Read `pdf-verify/apply-problems.json` if it exists. Then report to the user:
- batches and images run, by kind, and the model used;
- verdict counts;
- your spot-check result;
- the `pdf_verification` gate: extractor accuracy against the 98% threshold;
- affiliation coverage before and after;
- any new extractor failure pattern worth fixing in `pdf_affiliations.py`.

After a pilot, ask before running the rest.
