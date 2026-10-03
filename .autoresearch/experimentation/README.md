# Experimentation Workspace

This directory holds active, isolated experiment workspaces created by the
Sentinel. Each attempt has one `PROGRAM.md`, a read-only copy of
`LOGBOOK.json`, a `RESULT.json` for the hypothesis checkpoint and implementation
summary, and an isolated copy of the target project under `project/`. Build and
evaluation logs may appear after the agent returns.

Contents other than this README are gitignored. Sentinel owns workspace
creation and cleanup; do not use this directory as the durable experiment
history. Record reusable findings in the root `LOGBOOK.json`, and promote
accepted candidates to `approved/`.
