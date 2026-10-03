# Integration Guidelines for Future Models

This file explains how to connect Sentinel to a target project's evaluator.
Sentinel is implemented in Python regardless of the target
project's language. It invokes the target project's build and evaluation tools
as argument arrays from an isolated copy of that project.

## Workspace naming and contents

For configured major version `M`, minor version `N`, and `file_prefix` `P`,
Sentinel creates:

```text
.autoresearch/experimentation/VM-N_P/
  PROGRAM.md                 the single generated agent instruction file
  LOGBOOK.json               read-only copy of durable findings and its guide
  RESULT.json                hypothesis checkpoint and implementation summary
  project/                   full latest-baseline project copy
    <editable files>         configured project-relative edit allowlist
```

For example, major version `1`, minor version `4`, and prefix `Solver` produce
`.autoresearch/experimentation/V1-4_Solver/`.

`file_prefix` is a safe filename-like label used in the attempt directory name;
it does not rename project files. `[candidate].editable_files` is an explicit
array of project-relative paths the agent may modify or create. Files outside that list
remain available as read-only context. Before forming a hypothesis, the agent
reads every file in the sandbox, including the complete project copy. It writes
its hypothesis to `RESULT.json` before making code changes, then fills its
implementation summary. The logbook copy is read-only, and Sentinel compares
the candidate project with its approved source, rejecting changes outside the
allowlist.

The Codex Python SDK opens a `Sandbox.workspace_write` thread with the attempt
directory as its working directory. The copied `project/` tree is the candidate source; only allowlisted files
are writable by the agent. After the agent returns, Sentinel creates a separate
`evaluation-project/` copy for build/evaluation, leaving the candidate snapshot
clean for promotion. No external project root or checkout is consulted during
later attempts.

## Evaluator integration contract

The evaluator is project-specific. Configure its command in
`[commands].evaluate`; it may run tests, a benchmark, a simulation, a match, or
another measurable procedure. If useful, the evaluator should write its full
run log (for example, per-game records, simulation traces, or benchmark
samples) into the copied project or another path inside the attempt directory.
Keep verbose/raw evidence in logs; do not make the orchestrator infer a result
from free-form prose.

The evaluator must write the path configured by
`[evaluation].result_file`, relative to the copied project root, as a strict
JSON object with this minimum shape:

```json
{
  "schema_version": 1,
  "status": "completed",
  "metrics": {
    "score": 0.82
  },
  "failures": [],
  "artifacts": ["logs/run.csv"]
}
```

`status` must be `completed`; `failures` must be an array; configured metrics
must be finite numbers. `[metric].json_path` selects the metric using
dot-separated object keys, such as `metrics.score`. Include evaluator metadata
that makes the result auditable when relevant: sample count, seed, evaluator
version, environment, and relative paths to raw logs. Keep those extra fields
inside the JSON result so they travel with the attempt record. List important
run files in `artifacts` as paths relative to the copied project root. Sentinel
copies declared artifacts into approved records; rejected attempts retain the
whole isolated project and its logs.

Sentinel deletes a stale result file before evaluation. A non-zero exit,
timeout, missing result file, invalid JSON, incomplete status, missing metric,
or malformed `failures` field is an evaluation failure and cannot approve a
candidate.

## Approval policy

Approval is a deterministic Python decision by default, not an LLM vote. Sentinel establishes an initial baseline by building/evaluating the
user-populated seed project, then compares each candidate with the latest
approved full-project snapshot's metric under the same configured evaluator. A candidate must report
no evaluator failures and improve the metric in the configured direction by
more than `approval.minimum_improvement`. Only an approved candidate becomes
the complete seed for the next attempt. Build/evaluation failure or a failed
metric comparison leaves the latest approved project snapshot unchanged.

The agent returns control after its implementation pass and does not receive
the evaluator result or approval decision. Python records and acts on the
structured evaluator result directly.
For a target whose acceptance rule needs domain-specific gates—such as a
maximum crash rate, confidence interval, or multiple metrics—extend
`run_sentinel.py`'s `approval_decision` function and document the required structured
fields here. Do not ask the model to judge a numeric result if a clear formula
can be implemented and audited in code.

Stochastic evaluators should use fixed seeds and/or enough repeated samples to
make comparisons meaningful. Sentinel makes orchestration and bookkeeping
repeatable; it cannot make a noisy test environment or probabilistic model
output deterministic.

If Sentinel finds an interrupted workspace for the next version, it checks
`RESULT.json` and compares the candidate's allowlisted files with the latest
approved project. It preserves and evaluates the workspace only when it has a
non-empty hypothesis, a non-empty implementation summary, and at least one
actual allowlisted source change. A hypothesis alone is only an early
checkpoint; it does not show that implementation finished. Without all three
signals, Sentinel skips evaluation and state updates. On the next run it
recreates that same version from the latest approved snapshot and asks the
agent to choose a different hypothesis from the one in the interrupted
checkpoint. An agent failure before recording a hypothesis also leaves version
state unchanged, so the continuous loop retries that version. Configuration
errors and failure to establish a valid baseline stop the run because no
meaningful candidate decision can be made.

## Durable artifacts

- `.autoresearch/project/V<major>-<minor>/` is the user-populated initial full
  project seed. The baseline phase snapshots it to `approved/V<major>-<minor>/project/`.
- `approved/V<major>-<minor>/project/` stores the complete approved project
  tree. The next attempt clones that entire snapshot, so accepted changes
  accumulate. Version folders also contain the structured evaluator result,
  command logs, agent `RESULT.json`, and declared artifacts.
- `approved/state.json` tracks the latest approved snapshot and next version;
  `approved/baseline.json` stores the active reference measurement.
- `.autoresearch/rejected/<attempt>/` stores rejected workspaces and raw output
  locally; these contents are gitignored.
- `LOGBOOK.json` stores project guidance and structured experiment records,
  including metrics for graphing. Preserve full simulation or
  benchmark logs as attempt artifacts and summarize their relevant findings in
  the logbook.
