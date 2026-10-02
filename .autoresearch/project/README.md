# Initial Project Seed

Run `python run_sentinel.py --setup-project` to create the configured
initial version folder, by default `V1-0/`, beside this file. Copy the complete
target project into that folder: source, project files, tests, evaluator, and
anything else needed by the configured build and evaluation commands. Do not
copy its nested `.git` directory; the Sentinel fork tracks this experiment
setup, and project Git metadata is not part of the candidate snapshot.

Then set `[candidate].editable_files` in the Sentinel root `config.toml` to the
project-relative allowlist of paths the agent may edit or create, then configure
build/evaluation commands, result JSON, metric, and approval threshold. Sentinel starts from this seed folder
and then clones the latest approved full project
snapshot for each new attempt.

The initial seed becomes the `V<major>-<minor>` baseline snapshot after its
first successful baseline evaluation. Each approved experiment is saved as a
complete project snapshot under `approved/` and becomes the source for the next
attempt. Rejected candidates do not replace that source. The initial seed is
tracked in the Sentinel fork; active workspaces and rejected runs are ignored.
