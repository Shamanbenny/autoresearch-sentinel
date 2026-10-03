# Autoresearch Sentinel

Autoresearch Sentinel is a system for persistent, evaluation-driven
experimentation. It is intended for any project where candidate changes can be
judged by a repeatable command and measurable result: tests, benchmarks,
simulations, matches, or other domain-specific evaluators.

## Relationship to Karpathy's autoresearch

Sentinel is an improvement-oriented fork of [Andrej Karpathy's
autoresearch](https://github.com/karpathy/autoresearch), which originally demonstrates
autonomous experimentation on a compact single-GPU LLM training setup. That is
a focused and useful machine-learning research paradigm: the agent edits
training code, runs a bounded training job, and compares a validation metric.
Sentinel carries the evaluate-and-keep-or-reject idea into projects beyond
machine learning, where the evaluator might instead be a test suite, benchmark,
simulation, or match.

The other limitation Sentinel addresses is who owns the loop. In the original
workflow, the agent is instructed to keep experimenting indefinitely. That
instruction lives in the agent's prompt and context. An overnight run therefore
depends on the agent continuing to remember and follow it across a long session.
As context grows or is compressed, the loop instruction can be lost among
other details; the agent can also stop after a completed task or produce an
unexpected response. These are ordinary failure modes of relying on a
probabilistic model to control a persistent process, and make unattended runs
less reliable than the experiment design suggests.

Sentinel puts continuation under code control: the agent
handles one bounded hypothesis, while code outside the model runs evaluation,
records the result, persists progress, and schedules the next attempt. After a
process interruption, Sentinel reuses a workspace only when `RESULT.json`
contains a non-empty hypothesis, implementation summary, and actual allowlisted
source change. If a hypothesis exists but implementation is incomplete,
Sentinel refreshes only the workspace's `project/` copy from the latest
approved snapshot and preserves `RESULT.json`, so the next turn continues the
same hypothesis. If no hypothesis was recorded, Sentinel recreates the sandbox
from the latest approved seed. It does not resume the exact same Codex turn.
Agent output and experiment results remain probabilistic;
the goal is reliable orchestration, not deterministic discovery.
As the developer, my aim is to remove uncertainty from the parts software can
control by making continuation, state transitions, evaluation, and
recordkeeping deterministic. That more deterministic orchestration is the
improvement Autoresearch Sentinel sets out to provide.

## Current status

The Sentinel (the Python Controller) is implemented in `run_sentinel.py`. It
creates isolated workspaces, invokes the Codex Python SDK, runs configured
build/evaluation commands, applies Sentinel-owned approval, and loops until
interrupted (or `--once` is used). The current branch is configured with a
CPU-only maze-pathfinder demonstration project.

## Benefits of Autoresearch Sentinel

- **Works beyond machine learning:** use it wherever a repeatable command can
  measure a candidate, including tests, benchmarks, simulations, and matches.
- **Reliable long-running orchestration:** Sentinel owns continuation, so the
  agent does not have to remember to keep its own loop running across a long
  context or overnight session.
- **Bounded agent work:** each turn proposes one hypothesis, implements it, and
  returns control; evaluation and the next attempt happen outside the model.
- **Reduce carried-forward context:** Sentinel starts a fresh Codex thread for
  each experiment and supplies the current sandbox, program, and logbook instead
  of the preceding experiments' full agent conversation. Prior conversation
  inputs count toward input tokens and context limits in multi-turn model
  workflows, so leaving old experiment transcripts out can reduce per-experiment
  context and input-token use ([OpenAI conversation-state guide](https://developers.openai.com/api/docs/guides/conversation-state),
  [token definitions](https://help.openai.com/en/articles/4936856-understanding-and-counting-tokens)).
  This reduces carried history; it does not guarantee lower total token usage,
  since each attempt still needs the current project context.
- **Cumulative improvements:** every attempt starts from the latest approved
  full-project snapshot, so accepted changes build on each other.
- **Reviewable experiments:** approved snapshots, structured results, metrics,
  command logs, and the logbook give the setup a durable record.
- **Project-specific toolchains:** configure build and evaluator commands
  without requiring the target project to use the same language as Sentinel.

## Guardrails enforced by Sentinel

- **Explicit edit allowlist:** `candidate.editable_files` lists the only
  project paths the agent may edit or create. Other project files remain
  readable as context.
- **Post-turn change check:** after the agent returns, Sentinel compares the
  candidate project against its latest approved source. If any non-allowlisted
  file was added, removed, or changed, Sentinel rejects the attempt. It also
  checks that sandbox instruction and logbook files were not changed.
- **Implementation checkpoint for recovery:** the agent writes its hypothesis
  before editing and its implementation summary after making a change. Sentinel
  evaluates a preserved candidate only when both fields are present and an
  allowlisted project file actually changed. If interrupted earlier, it refreshes
  only `project/` and preserves the hypothesis in `RESULT.json` for continuation.
- **Isolated evaluation:** build and evaluation commands run on a separate copy
  of the candidate, leaving the candidate snapshot clean for promotion.
- **Structured, Sentinel-owned approval:** Sentinel validates the evaluator's
  JSON result and applies the configured metric, direction, threshold, and
  failure rules. The agent cannot approve its own change.
- **Bounded execution:** agent, build, and evaluation commands have configured
  timeouts. `--once` runs a single attempt; otherwise Sentinel continues until
  interrupted.

These guardrails make orchestration and state changes predictable. They do not
make a probabilistic agent or a noisy evaluator deterministic, and a candidate
still needs a useful, repeatable evaluation contract.

## Repository layout

```text
README.md                    project overview and status
config.toml                  language-neutral project/run configuration
run_sentinel.py              Sentinel
requirements.txt             Codex Python SDK and Python 3.10 TOML support
.autoresearch/project/       initial full-project seed setup
GUIDELINE.md                 evaluator integration and approval contract
PROGRAM.md                   bounded task instructions for the agent
LOGBOOK.json                 tracked project guidance and structured experiment data
plot_logbook.py              dependency-free SVG charts from experiment metrics
approved/                    tracked accepted candidate snapshots and evidence
.autoresearch/experimentation/ ignored active workspaces and hypotheses
.autoresearch/rejected/       ignored rejected candidates and raw outputs
```

The experiment and rejected folders are local runtime data and are gitignored.
The approved folder and logbook are version-controlled so accepted results and
their durable context can be reviewed and shared.

## One fork per experiment setup

Fork Autoresearch Sentinel once for each experiment setup. A setup has its own
target project, evaluator commands and metric, agent configuration, version
sequence, approved candidates, rejected attempts, and active experimentation
workspaces. Keeping those together in one fork prevents separate experiments
from overwriting or mixing configuration and candidate state. To run another
independent setup, create another fork rather than sharing the same
`config.toml`, `approved/`, or `.autoresearch/` directories.

## CPU-only demo: maze pathfinder

This branch includes a complete Python project under
`.autoresearch/project/V1-0/`. Its baseline `solver.py` uses breadth-first
search (BFS). The evaluator checks 17 fixed mazes, verifies every route is
legal and shortest using an independent oracle, and minimizes the total number
of nodes explored. No GPU or third-party Python packages are needed for the
candidate or evaluator.

The agent may edit only `solver.py`; it can read `evaluate.py`, `mazes.json`, and
the project README as context. The evaluator and cases are protected by
`candidate.editable_files = ["solver.py"]`.

From the `autoresearch-sentinel/` root, run one baseline plus one experiment:

```bash
python run_sentinel.py --once --prompt "Find one deterministic change to reduce total nodes explored while preserving shortest-path correctness on every fixed maze."
```

Sentinel first measures V1-0, then asks the agent to implement V1-1 and evaluates
it. To let the loop continue beyond the first attempt, remove `--once`. The
config is already set for this demo.

## Usage

In the fork for this setup, configure `config.toml` for one target project and
evaluator. Install Sentinel dependencies in a project-local virtual
environment. On Debian or Ubuntu, install `python3-full` first if `venv` is not
available (`sudo apt install python3-full`).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, use `py -m venv .venv`, then
`.venv\Scripts\Activate.ps1`, followed by `python -m pip install -r requirements.txt`.
Run Sentinel from the activated environment. This avoids installing packages
into an OS-managed Python, which may reject system-wide `pip` installs under
PEP 668.

Create the initial project folder:

```bash
python run_sentinel.py --setup-project
```

By default, this creates `.autoresearch/project/V1-0/`. Copy the complete
target project into that folder, including its build files, tests, and
evaluator, but omit its nested `.git` directory. Remove the placeholder
`.gitkeep`, then configure `editable_files`, build/evaluation commands, and the
metric in `config.toml` as described below. The source folder is the initial
seed; each approved attempt thereafter becomes the new full-project seed.

Preview the isolated workspace without invoking the agent, build, or evaluator:

```bash
python run_sentinel.py --config config.toml --dry-run
```

The preview remains in `.autoresearch/experimentation/` for inspection. If it
has no hypothesis, the next normal run recreates that workspace from the latest
approved project for the same candidate version. If a hypothesis was recorded
but implementation is incomplete, the next run refreshes only `project/`,
preserves `RESULT.json`, and continues the same hypothesis. Evaluation still
requires a non-empty implementation summary and an actual allowlisted source
change.

Inspect `.autoresearch/experimentation/<candidate>/`, then start one complete
baseline/candidate cycle:

```bash
python run_sentinel.py --config config.toml --once
```

On the first normal run, Sentinel evaluates the initial `V1-0` seed and saves
an immutable full-project baseline snapshot under `approved/V1-0/project/`.
The first experiment is `V1-1`. Each later attempt copies the latest approved
full project snapshot; when approved, its entire project tree is stored under
`approved/<version>/project/` and becomes the seed for the next version. A
rejected attempt does not change the latest approved seed. `approved/state.json`
tracks the latest approved version, its metric, and the next candidate version.

Remove `--once` to run continuously. Sentinel starts each bounded
agent attempt, evaluates it, records the approval decision, and starts the next
attempt without asking the agent whether to continue. Stop the process with
Ctrl+C. The Codex SDK uses the configured model and the host's existing Codex
login/runtime.

Generate an SVG chart of the metric history, including rejected attempts:

```bash
python plot_logbook.py
```

After Sentinel has recorded at least one numeric metric, the script reads
`LOGBOOK.json`, includes every record with a numeric value,
colors approved, rejected, baseline, and other points separately, and connects
approved points only. Rejected points do not have metric-value labels. The
x-axis numbers each plotted record, and approved points show only the version
part of their candidate name (for example, `V1-9`). Label placement follows the
metric direction: for lower-is-better metrics, values and version labels appear
above and slightly right of their points; for higher-is-better metrics, values
appear below-right and version labels angle down-right at 45 degrees. Charts
contain up to 50 records each, with later pages named
`sentinel-research-plot-2.svg`, `sentinel-research-plot-3.svg`, and so on.
Numbering continues across pages. By default, the first chart is
`sentinel-research-plot.svg` at the repository root. Use `--metric NAME` when
the logbook contains multiple metrics, `--logbook PATH` to read another JSON
logbook, or `--output PATH` to choose the base SVG path. It uses only the Python
standard library.

### Command-line parameters

| Parameter | Meaning |
| --- | --- |
| `--config PATH` | TOML configuration file. Defaults to the repository's `config.toml`. |
| `--setup-project` | Create the initial `V<major>-<minor>` project seed folder from `[project].seed_dir` and the configured starting version. Run once before adding the target project. |
| `--prompt TEXT` | Optional research direction included in the generated sandbox `PROGRAM.md`. The agent still makes one bounded change. |
| `--once` | Run baseline setup if needed, perform one attempt, then exit. |
| `--dry-run` | Prepare the isolated attempt workspace and exit without invoking Codex, building, or evaluating. |
| `-h`, `--help` | Show command help and exit. |

### `config.toml` parameters

| Setting | Required / default | Purpose |
| --- | --- | --- |
| `[project].seed_dir` | Default: `.autoresearch/project` | Parent folder for the initial full-project seed, named using the configured starting major/minor version. |
| `[agent].provider` | Required; currently `"codex"` only | Selects the agent SDK adapter. |
| `[agent].model` | Required | Model ID passed to the Codex SDK, such as the configured `gpt-6-luna` example. |
| `[agent].timeout_seconds` | Default: `1800` | Maximum duration of one agent implementation turn. |
| `[candidate].major_version`, `[candidate].minor_version` | Required; defaults: `1`, `0` | Version of the initial seed folder (`V1-0` by default). The first experiment advances to the next minor version. |
| `[candidate].editable_files` | Required | Array of project-relative file paths the agent may edit or create. Other project files remain available as read-only context. |
| `[candidate].file_prefix` | Required | Safe suffix containing letters, digits, `.`, `_`, or `-`. Attempt workspaces look like `V1-1_solver`; approved snapshots use the version only. |
| `[workspace].experimentation_dir` | Default: `.autoresearch/experimentation` | Parent directory for active attempt workspaces. |
| `[workspace].approved_dir` | Default: `approved` | Stores complete baseline/approved project snapshots, evaluator evidence, and `state.json`. |
| `[workspace].rejected_dir` | Default: `.autoresearch/rejected` | Stores rejected or interrupted attempts locally. |
| `[workspace].logbook` | Default: `LOGBOOK.json` | JSON record containing an embedded usage guide, project guidance, and structured experiment outcomes and metrics. |
| `[commands].build` | Default: `[]` (skip build) | Argument array for the target project's build command. |
| `[commands].evaluate` | Required | Argument array for the evaluator. It must write the configured JSON result file. |
| `[commands].timeout_seconds` | Default: `3600` | Timeout applied separately to build and evaluation commands. |
| `[evaluation].result_file` | Required | Result JSON path, relative to the copied project root. |
| `[metric].name` | Required | Human-readable metric name recorded in the JSON logbook and used by the graph script. |
| `[metric].json_path` | Required | Dot-separated JSON path to the numeric metric, for example `metrics.score`. |
| `[metric].direction` | Required: `minimize` or `maximize` | Defines which direction is an improvement. |
| `[approval].minimum_improvement` | Default: `0.0` | Required improvement versus the latest approved result; the candidate must exceed this threshold. |

Commands are argument arrays, not shell command strings. For example:

```toml
[commands]
build = ["dotnet", "build", "MyProject.sln"]
evaluate = ["python", "evaluate.py", "--result", "evaluation-result.json"]
timeout_seconds = 3600
```

Sentinel executes both commands from a separate evaluation copy of the
candidate project. Each argument may use `{project_root}` or `{candidate_file}`
substitutions. `{candidate_file}` resolves to the first path in
`candidate.editable_files`. An empty build array skips building; the evaluator
command cannot be empty. The candidate snapshot itself remains clean and is what gets
promoted when approved.

The evaluator must write a JSON object like this to
`[evaluation].result_file`:

```json
{
  "schema_version": 1,
  "status": "completed",
  "metrics": {"score": 0.82},
  "failures": [],
  "artifacts": ["logs/run.csv"]
}
```

Set `[metric].json_path = "metrics.score"` for this example. `failures` must
be an array and must be empty for approval. `artifacts` is optional; when
present, each path must identify a file inside the copied project. The complete
contract and approval extension point are described in
[`GUIDELINE.md`](GUIDELINE.md).

When no compatible baseline exists, Sentinel builds and evaluates the initial
seed to establish one. Each candidate is then evaluated against the latest
approved version. Missing or malformed evaluator output, a non-zero command,
reported failures, or insufficient metric improvement rejects that attempt.
Without `--once`, rejected attempts are recorded and the loop continues until
you interrupt it.

## Evaluation and approval

Each configured evaluation command must write the JSON response described in
[`GUIDELINE.md`](GUIDELINE.md). Sentinel checks its schema, status, failures,
configured numeric metric, and any declared artifact paths. When no baseline
exists, the first run builds and measures the initial `V<major>-<minor>` seed
to establish a baseline snapshot under `approved/`. Each approved attempt saves
the complete updated project tree; the next candidate is cloned from that
snapshot, so improvements accumulate. Candidates are compared to the latest approved metric using
`direction` and `minimum_improvement`; only Sentinel makes the approval decision.
The sandbox agent returns after implementation and receives no evaluation
result or approval decision. Projects with extra acceptance gates should extend
`approval_decision()` and document their result fields in the guideline.

## Agent workflow contract

Before each attempt, the agent reads its generated `PROGRAM.md`, stable
read-only `LOGBOOK.json`, and every file in the isolated project snapshot under
`.autoresearch/experimentation/`. Before editing, it records its hypothesis in
`RESULT.json`; then it edits only paths listed in `candidate.editable_files`
and records its implementation summary in `RESULT.json`. Sentinel evaluates an
interrupted attempt only when the summary is present and at least one allowed
project file actually changed. If only the hypothesis checkpoint exists,
Sentinel refreshes the project copy but preserves that hypothesis for the next
turn; it does not replace it with a new one.
Sentinel runs evaluation and moves the attempt to `approved/` or `.autoresearch/rejected/` according to the configured
rule. It appends a structured outcome and evaluator metrics to `LOGBOOK.json`.

Agents must not run the persistent loop themselves or decide whether an
experiment passed. The Sentinel enforces the configured parts of this
contract.
