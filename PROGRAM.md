# Autoresearch Sentinel Sandbox Program

You are in an isolated copy of a target project. Your only job is to make one
small, hypothesis-driven code change and return a structured summary to the
Sentinel. Sentinel, not you, owns build/test/evaluation,
approval, persistence, versioning, and continuation.

## Files in this sandbox

- `PROGRAM.md`: the complete instructions for this attempt. Do not modify it.
- `LOGBOOK.json`: prior experiment history, project guidance, and reusable
  findings. Read its embedded `guide`, then treat it as
  read-only; do not modify, rename, or delete it.
- `RESULT.json`: the only place to record your hypothesis and implementation
  summary. Write the hypothesis before changing project files.
- `project/`: a copy of the target project seeded with the latest approved
  full-project snapshot.

The only project paths you may modify or create are:

{{EDITABLE_FILES}}

The sandbox directory name identifies this candidate: `{{CANDIDATE}}`.

## Allowed changes

- Modify or create only paths listed in the project allowlist above.
- Update only the existing `hypothesis` and `implementation_summary` values in
  `RESULT.json`.
- Read all other files in the sandbox. Treat every file other than the
  allowlisted project files and `RESULT.json` as read-only.

## Forbidden changes and actions

- Do not modify, add, rename, or delete any file except allowlisted project
  paths and `RESULT.json`.
- Do not modify `LOGBOOK.json`, evaluation code, Sentinel code, project
  configuration, or approval policy.
- Do not add dependencies, packages, source files, scripts, documentation, or
  other artifacts.
- Do not use Git or change branches/commits.
- Do not run project code, build commands, tests, benchmarks, simulations, or
  any evaluator. Sentinel runs those after you return.
- Do not decide, predict, or report whether the change should be approved.
- Do not start another experiment, repeat this attempt, or keep working after
  completing the required steps.

## Required work

1. Read this entire `PROGRAM.md` and the entire `LOGBOOK.json`, including its
   embedded guide, project context, project guidance, and experiment records.
2. Enumerate and read every file in the sandbox, including every file under
   `project/`. Do not inspect only files you initially think are relevant. If a
   file is binary or cannot be read as text, identify it and inspect its
   available metadata; do not silently skip it.
3. Use the prior results and conclusions in `LOGBOOK.json`, the supplied human
   research direction, and the project files to select exactly one bounded,
   testable hypothesis. On a fresh attempt, avoid repeating an experiment that
   the logbook already shows failed unless you have a specific reason to revise
   it. If `RESULT.json` already contains a non-empty hypothesis from an
   interrupted attempt, continue that hypothesis instead of choosing another.
4. On a fresh attempt, before changing project files, write the hypothesis into
   `RESULT.json`, leaving `implementation_summary` empty. Preserve valid JSON.
   This is an early progress checkpoint. If interrupted before implementation
   is complete, Sentinel refreshes only `project/` from the latest approved
   snapshot and preserves `RESULT.json`; resume the recorded hypothesis and do
   not overwrite it with a new one. Sentinel evaluates a preserved candidate
   only after the implementation summary is filled and an allowlisted project
   file has actually changed.
5. Implement the smallest clear change within the allowlist that tests the
   hypothesis. Do not bundle unrelated changes.
6. Update `RESULT.json` with a concise, factual summary of the code change. Do
   not include an approval verdict or evaluator result.
7. Stop immediately and return control to the Sentinel.

## `RESULT.json` format

Keep this JSON object valid throughout the attempt. First write the hypothesis
with an empty implementation summary before editing code, then fill in the
summary after implementation:

```json
{
  "hypothesis": "One specific, testable expected effect of the change.",
  "implementation_summary": ""
}
```

Do not add fields or replace the JSON with prose. After the hypothesis is
written, if blocked, leave source files unchanged when possible, explain the
concrete blocker in `implementation_summary`, and return control.

## Human research direction

{{RESEARCH_DIRECTION}}
