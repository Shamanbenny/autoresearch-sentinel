#!/usr/bin/env python3
"""
Autoresearch Sentinel's configurable experiment loop.

==========================================================================
TARGET-PROJECT SETUP: CHECK THESE ITEMS FOR EVERY NEW PROJECT
==========================================================================

Most per-project changes belong in config.toml, not in this file:

1. [project].seed_dir
   Set the directory that will contain the initial full project snapshot,
   created by --setup-project as V<major>-<minor>.

2. [candidate].editable_files and file_prefix
   editable_files is the explicit project-relative allowlist the agent may edit.
   Each approved version stores the complete project snapshot, so accepted
   changes carry forward cumulatively. The workspace is named
   V<major>-<minor>_<file_prefix>.

3. [commands].build and [commands].evaluate
   Supply argument arrays for the target toolchain. Commands execute inside
   the isolated project copy. The evaluator must write [evaluation].result_file
   as JSON with schema_version=1, status="completed", a failures array, the
   configured numeric metric, and (optionally) project-relative artifacts.
   Emit raw benchmark/simulation logs as artifacts when they are needed to
   audit a result. Use {project_root} / {candidate_file} substitutions if
   useful. An empty build array deliberately skips the build step.

4. [metric] and [approval].minimum_improvement
   Set the JSON metric path, name, direction, and required improvement. The
   default approval rule is intentionally generic: no reported failures and
   improvement beyond the threshold versus the latest approved result. For
   domain-specific gates (multiple metrics, safety ceilings, confidence bounds,
   etc.), change approval_decision() and document the required evaluator fields
   in GUIDELINE.md. Approval remains a Python decision; the model's opinion is
   never authoritative.

5. [agent] and PROGRAM.md
   The current SDK adapter supports Codex only. Set the model and optional
   codex_bin for the runtime available on the host. Edit PROGRAM.md when the
   target needs different research instructions or constraints; the populated
   PROGRAM.md is the only agent instruction file in each sandbox.

6. [workspace]
   Set separate paths for experimentation, approved snapshots, rejected
   attempts, and the logbook. Keep the active/rejected directories ignored by
   Git and approved evidence reviewable.

Do not change the controller for ordinary project differences. Modify its
evaluator contract, approval_decision(), candidate file allowlist, or agent
adapter only when the target project cannot be expressed by the settings above.
See GUIDELINE.md for the complete evaluator/workspace integration contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 support
    import tomli as tomllib


SENTINEL_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = SENTINEL_ROOT / "config.toml"
PROGRAM_PATH = SENTINEL_ROOT / "PROGRAM.md"


class ExperimentError(RuntimeError):
    pass


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ExperimentError(f"Cannot read config {path}: {exc}") from exc

    for section in ("project", "agent", "candidate", "workspace", "commands", "evaluation", "metric", "approval"):
        if not isinstance(config.get(section), dict):
            raise ExperimentError(f"Missing [{section}] section in {path}")
    safe_relative_path(str(config["project"].get("seed_dir", "")), "project.seed_dir")
    if not config["commands"].get("evaluate"):
        raise ExperimentError("Set [commands].evaluate to the evaluator command array.")
    if config["agent"].get("provider") != "codex":
        raise ExperimentError("This initial orchestrator supports agent.provider = 'codex'.")
    agent_timeout = config["agent"].get("timeout_seconds", 1800)
    if isinstance(agent_timeout, bool) or not isinstance(agent_timeout, int) or agent_timeout < 1:
        raise ExperimentError("agent.timeout_seconds must be a positive integer.")
    if config["metric"].get("direction") not in {"minimize", "maximize"}:
        raise ExperimentError("[metric].direction must be 'minimize' or 'maximize'.")
    if not config["metric"].get("json_path"):
        raise ExperimentError("Set [metric].json_path to the metric location in evaluator JSON.")
    if not config["evaluation"].get("result_file"):
        raise ExperimentError("Set [evaluation].result_file to the evaluator JSON result path.")
    for key in ("build", "evaluate"):
        command = config["commands"].get(key, [])
        if not isinstance(command, list) or any(not isinstance(part, str) for part in command):
            raise ExperimentError(f"[commands].{key} must be an array of strings.")
    timeout = config["commands"].get("timeout_seconds", 3600)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise ExperimentError("[commands].timeout_seconds must be positive.")
    for key in ("experimentation_dir", "approved_dir", "rejected_dir", "logbook"):
        safe_relative_path(str(config["workspace"].get(key, "")), f"workspace.{key}")
    safe_relative_path(str(config["evaluation"]["result_file"]), "evaluation.result_file")
    for key in ("major_version", "minor_version"):
        value = config["candidate"].get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ExperimentError(f"candidate.{key} must be a non-negative integer.")
    editable_files = config["candidate"].get("editable_files")
    if not isinstance(editable_files, list) or not editable_files:
        raise ExperimentError("candidate.editable_files must be a non-empty array of project-relative paths.")
    normalized_files = []
    for item in editable_files:
        if not isinstance(item, str) or not item.strip():
            raise ExperimentError("Every candidate.editable_files entry must be a non-empty path string.")
        relative = safe_relative_path(item, "candidate.editable_files")
        if not relative.name:
            raise ExperimentError(f"candidate.editable_files entries must identify files: {item}")
        if relative.as_posix() in normalized_files:
            raise ExperimentError(f"candidate.editable_files contains a duplicate path: {item}")
        normalized_files.append(relative.as_posix())
    candidate_name(
        int(config["candidate"]["major_version"]),
        int(config["candidate"]["minor_version"]) + 1,
        str(config["candidate"].get("file_prefix", "")),
    )
    if not isinstance(config["agent"].get("model"), str) or not config["agent"]["model"].strip():
        raise ExperimentError("agent.model must be a non-empty model ID.")
    return config


def log_section(title: str) -> None:
    """Print a stable, highly visible boundary in the controller output."""
    print(f"=====\n{title}\n=====", flush=True)


def safe_relative_path(value: str, label: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ExperimentError(f"{label} must be a relative path inside the project: {value}")
    return path


def candidate_name(major: int, minor: int, prefix: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", prefix):
        raise ExperimentError("candidate.file_prefix may contain only letters, digits, '.', '_' and '-'.")
    return f"V{major}-{minor}_{prefix}"


def version_label(major: int, minor: int) -> str:
    return f"V{major}-{minor}"


def setup_project(config_path: Path) -> Path:
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ExperimentError(f"Cannot read config {config_path}: {exc}") from exc
    project = raw.get("project", {})
    candidate = raw.get("candidate", {})
    seed_parent_rel = safe_relative_path(str(project.get("seed_dir", ".autoresearch/project")), "project.seed_dir")
    major = int(candidate.get("major_version", 1))
    minor = int(candidate.get("minor_version", 0))
    seed_parent = (config_path.parent / seed_parent_rel).resolve()
    seed_project = seed_parent / version_label(major, minor)
    seed_project.mkdir(parents=True, exist_ok=True)
    keep = seed_project / ".gitkeep"
    if not any(seed_project.iterdir()):
        keep.touch()

    instructions = seed_parent / "README.md"
    if not instructions.exists():
        instructions.write_text(
            "# Initial Project Seed\n\n"
            f"Place the target project's source and required project files in `{seed_project.name}/`, but omit its nested `.git` directory. Keep its source, "
            "build files, evaluator, tests, and any other files required by the configured "
            "commands. Remove `.gitkeep` after adding the project. Set "
            "`candidate.editable_files` to the project-relative files the agent may edit, "
            "then configure build/evaluation commands and the metric in the Sentinel root `config.toml`.\n",
            encoding="utf-8",
        )
    print(f"Created initial project seed folder: {seed_project}")
    print("Copy the complete target project into that folder, then configure editable_files and the evaluator.")
    return seed_project


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"Cannot read structured JSON result {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExperimentError(f"Expected a JSON object in {path}.")
    return value


def metric_value(result: dict[str, Any], config: dict[str, Any]) -> float:
    value: Any = result
    for key in config["metric"]["json_path"].split("."):
        if not isinstance(value, dict) or key not in value:
            raise ExperimentError(f"Evaluator result is missing metric path {config['metric']['json_path']!r}.")
        value = value[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ExperimentError("Configured evaluator metric must be a finite number.")
    return float(value)


def validate_evaluation(result_path: Path, config: dict[str, Any], project_dir: Path) -> tuple[dict[str, Any], float]:
    result = read_json(result_path)
    if type(result.get("schema_version")) is not int or result.get("schema_version") != 1:
        raise ExperimentError("Evaluator JSON must set schema_version to 1.")
    if result.get("status") != "completed":
        raise ExperimentError("Evaluator JSON status must be 'completed'.")
    failures = result.get("failures")
    if not isinstance(failures, list):
        raise ExperimentError("Evaluator JSON must include a 'failures' array.")
    artifacts = result.get("artifacts", [])
    if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
        raise ExperimentError("Evaluator JSON 'artifacts' must be an array of project-relative paths.")
    for item in artifacts:
        artifact = project_dir / safe_relative_path(item, "evaluator artifact")
        if not artifact.is_file() or not artifact.resolve().is_relative_to(project_dir.resolve()):
            raise ExperimentError(f"Declared evaluator artifact is missing or outside the project: {item}")
    return result, metric_value(result, config)


def command_argv(command: list[str], project_dir: Path, candidate_file: Path) -> list[str]:
    values = {"project_root": str(project_dir), "candidate_file": str(candidate_file)}
    argv = []
    for part in command:
        for name, value in values.items():
            part = part.replace("{" + name + "}", value)
        argv.append(part)
    return argv


def run_command(command: list[str], project_dir: Path, candidate_file: Path, log_path: Path, timeout: int) -> bool:
    argv = command_argv(command, project_dir, candidate_file)
    if not argv:
        log_path.write_text("Skipped: no command configured.\n", encoding="utf-8")
        return True
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(argv, cwd=project_dir, text=True, stdout=log, stderr=subprocess.STDOUT)
            try:
                return_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                log.write(f"\nTimed out after {timeout}s.\n")
                print(f"Command timed out after {timeout}s: {' '.join(argv)}", file=sys.stderr)
                return False
            except KeyboardInterrupt:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                log.write("\nInterrupted by user.\n")
                raise
        print(f"$ {' '.join(argv)} -> exit {return_code}")
        return return_code == 0
    except OSError as exc:
        log_path.write_text(f"Could not start command: {exc}\n", encoding="utf-8")
        print(f"Could not start command {' '.join(argv)}: {exc}", file=sys.stderr)
        return False


def ignore_project_files(_directory: str, names: list[str]) -> set[str]:
    ignored = {".git", ".autoresearch", "__pycache__", ".venv", "venv", "bin", "obj", "node_modules", ".pytest_cache", ".tox", "target"}
    return ignored.intersection(names)


def copy_project(source: Path, target: Path, exclude_names: set[str] | None = None) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        return ignore_project_files(directory, names) | ((exclude_names or set()) & set(names))

    shutil.copytree(source, target, ignore=ignore, symlinks=False)


def file_manifest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        manifest[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def editable_project_changed(source: Path, candidate: Path, editable_files: list[Path]) -> bool:
    """Return whether the candidate contains any actual allowlisted source change."""
    source_manifest = file_manifest(source)
    candidate_manifest = file_manifest(candidate)
    return any(
        source_manifest.get(path.as_posix()) != candidate_manifest.get(path.as_posix())
        for path in editable_files
    )


def render_program(candidate: str, editable_files: list[str], prompt: str) -> str:
    template = PROGRAM_PATH.read_text(encoding="utf-8")
    direction = prompt.strip() or "None supplied; derive one hypothesis from the logbook and project files."
    rendered_files = "\n".join(f"- `project/{item}`" for item in editable_files)
    return (
        template.replace("{{CANDIDATE}}", candidate)
        .replace("{{EDITABLE_FILES}}", rendered_files)
        .replace("{{RESEARCH_DIRECTION}}", direction)
    )


def initial_seed_dir(config: dict[str, Any], config_path: Path) -> Path:
    parent = config_path.parent / safe_relative_path(config["project"]["seed_dir"], "project.seed_dir")
    version = version_label(int(config["candidate"]["major_version"]), int(config["candidate"]["minor_version"]))
    return (parent / version).resolve()


def latest_project_dir(
    state: dict[str, Any] | None,
    config: dict[str, Any],
    config_path: Path,
    artifact_root: Path,
) -> Path:
    if state and state.get("latest_approved", {}).get("project_dir"):
        relative = safe_relative_path(state["latest_approved"]["project_dir"], "latest approved project_dir")
        path = (artifact_root / relative).resolve()
    else:
        path = initial_seed_dir(config, config_path)
    if not path.is_dir():
        raise ExperimentError(f"Latest project snapshot does not exist: {path}. Run --setup-project or restore the approved snapshot.")
    return path


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json(path)


def append_logbook(
    path: Path,
    candidate: str,
    status: str,
    metric_name: str,
    value: float | None,
    reason: str,
    return_note: dict[str, Any],
    reported_metrics: dict[str, Any] | None = None,
    metric_direction: str | None = None,
) -> None:
    try:
        document = read_json(path) if path.exists() else read_json(SENTINEL_ROOT / "LOGBOOK.json")
    except ExperimentError as exc:
        raise ExperimentError(f"Cannot append experiment to JSON logbook {path}: {exc}") from exc
    experiments = document.get("experiments")
    if document.get("schema_version") != 1 or not isinstance(experiments, list):
        raise ExperimentError(f"JSON logbook {path} must have schema_version 1 and an experiments array.")
    project_context = document.setdefault("project_context", {})
    if isinstance(project_context, dict) and metric_direction in {"minimize", "maximize"}:
        directions = project_context.setdefault("metric_directions", {})
        if isinstance(directions, dict):
            directions[metric_name] = metric_direction

    metrics: dict[str, float | None] = {}

    def collect_metrics(value: Any, prefix: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                collect_metrics(item, f"{prefix}.{key}" if prefix else str(key))
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            metrics[prefix] = float(value)

    collect_metrics(reported_metrics or {})
    metrics[metric_name] = value
    approved = True if status == "approved" else False if status == "rejected" else None
    experiments.append(
        {
            "candidate": candidate,
            "status": status,
            "hypothesis": str(return_note.get("hypothesis", "not recorded")).replace("\n", " ").strip(),
            "implementation_summary": str(return_note.get("implementation_summary", "not recorded")).replace("\n", " ").strip(),
            "metrics": metrics,
            "decision": {
                "outcome": status,
                "approved": approved,
                "reason": reason,
            },
        }
    )
    atomic_json(path, document)


def approval_decision(value: float, baseline: float, config: dict[str, Any], failures: list[Any]) -> tuple[bool, str]:
    if failures:
        return False, f"Evaluator reported {len(failures)} failure(s)."
    raw_minimum = config["approval"].get("minimum_improvement", 0.0)
    if isinstance(raw_minimum, bool) or not isinstance(raw_minimum, (int, float)):
        raise ExperimentError("approval.minimum_improvement must be a finite non-negative number.")
    minimum = float(raw_minimum)
    if minimum < 0 or not math.isfinite(minimum):
        raise ExperimentError("approval.minimum_improvement must be a finite non-negative number.")
    if not math.isfinite(baseline):
        raise ExperimentError("Saved approved baseline metric is not finite.")
    direction = config["metric"]["direction"]
    improvement = value - baseline if direction == "maximize" else baseline - value
    if improvement <= minimum:
        return False, f"Improvement {improvement:.8g} did not exceed required minimum {minimum:.8g} (baseline {baseline:.8g})."
    return True, f"Improvement {improvement:.8g} exceeded required minimum {minimum:.8g} (baseline {baseline:.8g})."


def evaluator_signature(config: dict[str, Any], seed_dir: Path, editable_files: list[Path]) -> str:
    contract = {
        "seed_dir": str(seed_dir),
        "editable_files": [item.as_posix() for item in editable_files],
        "build": config["commands"].get("build", []),
        "evaluate": config["commands"]["evaluate"],
        "timeout_seconds": config["commands"].get("timeout_seconds", 3600),
        "result_file": config["evaluation"]["result_file"],
        "metric": config["metric"],
        "minimum_improvement": config["approval"].get("minimum_improvement", 0.0),
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def run_codex_turn(
    workspace: Path,
    config: dict[str, Any],
    prompt: str,
) -> str:
    try:
        from openai_codex import Codex, CodexConfig, Sandbox
    except ImportError as exc:
        raise ExperimentError("Install requirements.txt to use the Codex agent SDK.") from exc

    codex_bin = config["agent"].get("codex_bin")
    manager = Codex(CodexConfig(codex_bin=codex_bin)) if codex_bin else Codex()
    sandbox = Sandbox.workspace_write
    with manager as codex:
        log_section("Sandbox Agent started")
        thread = codex.thread_start(
            cwd=str(workspace),
            model=config["agent"]["model"],
            sandbox=sandbox,
        )
        turn = thread.turn(prompt, cwd=str(workspace), sandbox=sandbox)
        result_box: dict[str, Any] = {
            "error": None,
            "completed_status": None,
            "completed_error": None,
            "completed_usage": None,
            "completed_texts": [],
            "printed_response_prefix": False,
        }

        def consume_turn() -> None:
            try:
                for event in turn.stream():
                    method = getattr(event, "method", "unknown")
                    if method == "turn/started":
                        print("Codex turn started.", flush=True)
                    elif method == "item/agentMessage/delta":
                        delta = getattr(getattr(event, "payload", None), "delta", "")
                        if delta:
                            if not result_box["printed_response_prefix"]:
                                print("\n[Sandbox Agent response] ", end="", flush=True)
                                result_box["printed_response_prefix"] = True
                            print(delta, end="", flush=True)
                    elif method == "item/completed":
                        item = getattr(getattr(event, "payload", None), "item", None)
                        root = getattr(item, "root", item)
                        if getattr(root, "type", None) == "agentMessage":
                            text = getattr(root, "text", "")
                            if text:
                                result_box["completed_texts"].append(text)
                        else:
                            item_type = getattr(root, "type", "unknown")
                            print(f"\nCodex item completed: {item_type}", flush=True)
                    elif method == "turn/completed":
                        completed_turn = getattr(getattr(event, "payload", None), "turn", None)
                        result_box["completed_status"] = getattr(completed_turn, "status", None)
                        result_box["completed_error"] = getattr(completed_turn, "error", None)
                        result_box["completed_usage"] = getattr(completed_turn, "usage", None)
                    else:
                        # Keep less common SDK notifications visible without
                        # dumping potentially large payloads into the console.
                        print(f"Codex event: {method}", flush=True)
            except BaseException as exc:
                result_box["error"] = exc

        worker = threading.Thread(target=consume_turn, name="sentinel-codex-turn", daemon=True)
        worker.start()
        worker.join(timeout=int(config["agent"].get("timeout_seconds", 1800)))
        if worker.is_alive():
            try:
                turn.interrupt()
            except Exception:
                pass
            worker.join(timeout=5)
            raise ExperimentError("Codex turn timed out and the attempt workspace was preserved for retry.")
        if result_box["printed_response_prefix"]:
            print(flush=True)
        if result_box["error"] is not None:
            raise ExperimentError(f"Codex turn failed: {result_box['error']}")
        status = getattr(result_box["completed_status"], "value", result_box["completed_status"])
        if status != "completed":
            raise ExperimentError(
                f"Codex turn ended with status {status}: {result_box['completed_error']}"
            )
        if result_box["completed_usage"] is not None:
            usage = result_box["completed_usage"]
            if hasattr(usage, "model_dump"):
                usage = usage.model_dump(exclude_none=True)
            print(f"Codex usage: {json.dumps(usage, sort_keys=True, default=str)}", flush=True)
        log_section("Sandbox Agent finished")
        return (result_box["completed_texts"][-1] if result_box["completed_texts"] else "").strip()


def establish_baseline(
    seed_dir: Path,
    config: dict[str, Any],
    config_path: Path,
    editable_files: list[Path],
    baseline_path: Path,
    artifact_root: Path,
    state_path: Path,
    logbook_path: Path,
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    source_project = latest_project_dir(state, config, config_path, artifact_root)
    baseline_dir = artifact_root / config["workspace"]["approved_dir"]
    baseline_dir.mkdir(parents=True, exist_ok=True)
    initial_major = int(config["candidate"]["major_version"])
    initial_minor = int(config["candidate"]["minor_version"])
    seed_version = version_label(initial_major, initial_minor)
    initial_snapshot_root = baseline_dir / seed_version
    initial_snapshot = initial_snapshot_root / "project"
    if state is None and initial_snapshot.is_dir():
        # Recover a first-run interruption after the immutable baseline snapshot
        # was written but before approved/state.json was persisted.
        source_project = initial_snapshot
    print(f"Evaluating full project snapshot {source_project} to establish/update the baseline.")
    with tempfile.TemporaryDirectory(prefix="autoresearch-sentinel-baseline-") as temp:
        temp_root = Path(temp)
        project_dir = temp_root / "project"
        copy_project(source_project, project_dir)
        candidate_file = project_dir / editable_files[0]
        timeout = int(config["commands"].get("timeout_seconds", 3600))
        build_log = baseline_dir / "baseline-build.log"
        evaluation_log = baseline_dir / "baseline-evaluation.log"
        log_section("Baseline build started")
        if not run_command(config["commands"].get("build", []), project_dir, candidate_file, build_log, timeout):
            raise ExperimentError(f"Baseline build failed; inspect {build_log}.")
        log_section("Baseline evaluation started")
        result_path = project_dir / safe_relative_path(config["evaluation"]["result_file"], "evaluation.result_file")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.unlink(missing_ok=True)
        if not run_command(config["commands"]["evaluate"], project_dir, candidate_file, evaluation_log, timeout):
            raise ExperimentError(f"Baseline evaluation command failed; inspect {evaluation_log}.")
        result, value = validate_evaluation(result_path, config, project_dir)
        log_section("Baseline evaluation finished")
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)
        if result["failures"]:
            raise ExperimentError("Baseline evaluator reported failures; refusing to establish an invalid baseline.")
        baseline = {
            "schema_version": 1,
            "metric": config["metric"]["name"],
            "direction": config["metric"]["direction"],
            "value": value,
            "result": result,
            "seed_project": str(seed_dir),
            "source_project": str(source_project),
            "evaluator_signature": evaluator_signature(config, seed_dir, editable_files),
        }
        new_state = state is None
        state = state or {}
        if new_state:
            if not initial_snapshot.exists():
                copy_project(source_project, initial_snapshot)
            baseline_project_rel = initial_snapshot.relative_to(artifact_root).as_posix()
            state["latest_approved"] = {
                "version": seed_version,
                "project_dir": baseline_project_rel,
                "metric": value,
                "metric_name": config["metric"]["name"],
                "direction": config["metric"]["direction"],
            }
            state["next_major"] = initial_major
            state["next_minor"] = initial_minor + 1
            state["configured_major"] = initial_major
            state["seed_dir"] = seed_dir.relative_to(artifact_root).as_posix()
        elif state.get("configured_major") != int(config["candidate"]["major_version"]):
            state["configured_major"] = int(config["candidate"]["major_version"])
            state["next_major"] = int(config["candidate"]["major_version"])
            state["next_minor"] = int(config["candidate"]["minor_version"])
            state["latest_approved"]["metric"] = value
        else:
            state["latest_approved"]["metric"] = value
        state["latest_approved"]["metric_name"] = config["metric"]["name"]
        state["latest_approved"]["direction"] = config["metric"]["direction"]
        baseline["latest_approved_version"] = state["latest_approved"]["version"]
        baseline["latest_approved_project_dir"] = state["latest_approved"]["project_dir"]
        state["evaluator_signature"] = baseline["evaluator_signature"]
        atomic_json(baseline_path, baseline)
        atomic_json(state_path, state)
        shutil.copy2(result_path, baseline_dir / "baseline-result.json")
        shutil.rmtree(baseline_dir / "baseline-artifacts", ignore_errors=True)
        for artifact_name in result.get("artifacts", []):
            source = project_dir / artifact_name
            target = baseline_dir / "baseline-artifacts" / artifact_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        append_logbook(
            logbook_path,
            "baseline",
            "baseline",
            config["metric"]["name"],
            value,
            "Measured the latest approved seed as the reference for this evaluator configuration.",
            {"hypothesis": "Baseline measurement", "implementation_summary": "No candidate changes applied."},
            result.get("metrics", {}),
            config["metric"]["direction"],
        )
        return baseline


def execute_candidate(
    config: dict[str, Any],
    config_path: Path,
    seed_dir: Path,
    editable_files: list[Path],
    state: dict[str, Any] | None,
    baseline: dict[str, Any],
    prompt: str,
    dry_run: bool,
    artifact_root: Path,
    state_path: Path,
    logbook_path: Path,
) -> tuple[str, bool, float | None, str]:
    configured_major = int(config["candidate"]["major_version"])
    same_major = state is not None and state.get("configured_major", configured_major) == configured_major
    if state is None:
        major = configured_major
        minor = int(config["candidate"]["minor_version"]) + 1
    else:
        major = int(state.get("next_major", configured_major)) if same_major else configured_major
        minor = int(state.get("next_minor", config["candidate"]["minor_version"])) if same_major else int(config["candidate"]["minor_version"])
    name = candidate_name(major, minor, str(config["candidate"]["file_prefix"]))
    source_project = latest_project_dir(state, config, config_path, artifact_root)
    workspace_root = (artifact_root / config["workspace"]["experimentation_dir"]).resolve()
    workspace = workspace_root / name
    result_path_in_workspace = workspace / "RESULT.json"
    recovering = False
    recovered_result: dict[str, Any] = {}
    interrupted_hypothesis = ""
    if workspace.exists():
        try:
            recovered_result = read_json(result_path_in_workspace)
        except ExperimentError:
            recovered_result = {}
        has_hypothesis = (
            isinstance(recovered_result.get("hypothesis"), str)
            and bool(recovered_result["hypothesis"].strip())
        )
        has_implementation_summary = (
            isinstance(recovered_result.get("implementation_summary"), str)
            and bool(recovered_result["implementation_summary"].strip())
        )
        project_dir = workspace / "project"
        recovering = (
            has_hypothesis
            and has_implementation_summary
            and project_dir.is_dir()
            and editable_project_changed(source_project, project_dir, editable_files)
        )
        if recovering:
            print(f"Recovering {name}: implementation summary and source change found; evaluating the preserved candidate.")
        else:
            if has_hypothesis:
                interrupted_hypothesis = recovered_result["hypothesis"].strip()
            shutil.rmtree(workspace)
            if interrupted_hypothesis:
                print(
                    f"Discarded incomplete {name}: the hypothesis was recorded, but no completed implementation "
                    "with an allowlisted source change was found. Restarting from the latest approved snapshot."
                )
            else:
                print(f"Discarded incomplete {name}: no durable hypothesis; retrying from latest approved snapshot.")

    control_before: dict[str, str] = {}
    if not recovering:
        workspace.mkdir(parents=True)
        project_dir = workspace / "project"
        copy_project(source_project, project_dir)
        (workspace / "PROGRAM.md").write_text(render_program(name, [item.as_posix() for item in editable_files], prompt), encoding="utf-8")
        logbook_copy = workspace / "LOGBOOK.json"
        shutil.copy2(logbook_path, logbook_copy)
        logbook_copy.chmod(0o444)
        result_path_in_workspace.write_text(
            json.dumps({"hypothesis": "", "implementation_summary": ""}, indent=2) + "\n",
            encoding="utf-8",
        )
        control_before = {
            path: digest for path, digest in file_manifest(workspace).items()
            if not path.startswith("project/")
        }
    project_dir = workspace / "project"
    if dry_run:
        print(f"Prepared {workspace.relative_to(config_path.parent)}")
        return name, False, None, "dry run only"

    agent_error = ""
    agent_response = ""
    if not recovering:
        print(f"Prepared {workspace.relative_to(config_path.parent)}")
        try:
            agent_prompt = (
                "Follow PROGRAM.md exactly. Enumerate and read every file in the sandbox. Choose one bounded, "
                "testable hypothesis and write it to RESULT.json before changing project files. Then make the "
                "smallest change within candidate.editable_files, fill implementation_summary, and return control. "
                "Do not evaluate or decide approval."
            )
            if interrupted_hypothesis:
                agent_prompt += (
                    "\n\nThis is a clean restart after an interrupted attempt. The previous hypothesis was: "
                    f"{interrupted_hypothesis}\nChoose a different, testable hypothesis and do not repeat that change."
                )
            agent_response = run_codex_turn(
                workspace,
                config,
                agent_prompt,
            )
        except Exception as exc:
            agent_error = f"Agent turn failed: {exc}"
        try:
            checkpoint = read_json(result_path_in_workspace)
        except ExperimentError:
            checkpoint = {}
        has_checkpoint = isinstance(checkpoint.get("hypothesis"), str) and bool(checkpoint["hypothesis"].strip())
        has_implementation_summary = (
            isinstance(checkpoint.get("implementation_summary"), str)
            and bool(checkpoint["implementation_summary"].strip())
        )
        has_source_change = (project_dir.is_dir() and editable_project_changed(source_project, project_dir, editable_files))
        if has_checkpoint and has_implementation_summary and has_source_change:
            recovering = True
            recovered_result = checkpoint
            agent_error = ""
            print(f"{name}: implementation summary and source change found; evaluating the preserved candidate.")
        else:
            if has_checkpoint:
                interrupted_hypothesis = checkpoint["hypothesis"].strip()
                reason = (
                    "Agent stopped before completing an implementation summary and allowlisted source change; "
                    "the hypothesis checkpoint was preserved for a clean restart."
                )
            else:
                reason = agent_error or "Agent stopped before recording a hypothesis; retrying this version from the latest approved snapshot."
                shutil.rmtree(workspace, ignore_errors=True)
            print(f"{name}: {reason}", file=sys.stderr)
            if agent_response.strip():
                excerpt = agent_response.strip()
                if len(excerpt) > 1500:
                    excerpt = excerpt[:1500] + "… [truncated]"
                print(f"Agent final response before cleanup:\n{excerpt}", file=sys.stderr)
            elif not agent_error:
                print("The Codex turn completed without writing a hypothesis to RESULT.json.", file=sys.stderr)
            if has_checkpoint:
                print("Kept the checkpoint only to avoid repeating its hypothesis; no evaluation or state update was performed.", file=sys.stderr)
            else:
                print("Discarded the incomplete workspace and left version state unchanged.", file=sys.stderr)
            return name, False, None, reason

    baseline_files = file_manifest(source_project)
    candidate_files = file_manifest(project_dir)
    allowed_paths = {item.as_posix() for item in editable_files}
    unauthorized = [
        path for path in set(baseline_files) | set(candidate_files)
        if path not in allowed_paths and baseline_files.get(path) != candidate_files.get(path)
    ]
    if control_before:
        control_after = {
            path: digest for path, digest in file_manifest(workspace).items()
            if not path.startswith("project/")
        }
        unauthorized.extend(
            path for path in set(control_before) | set(control_after)
            if path != "RESULT.json" and control_before.get(path) != control_after.get(path)
        )
    reason = agent_error
    result: dict[str, Any] | None = None
    value: float | None = None
    approved = False
    if unauthorized:
        reason = f"Candidate changed files outside candidate.editable_files: {', '.join(sorted(unauthorized)[:8])}"

    return_note: dict[str, Any] = {"hypothesis": "not recorded", "implementation_summary": "not recorded"}
    try:
        return_note = read_json(result_path_in_workspace)
        if not isinstance(return_note.get("hypothesis"), str) or not return_note["hypothesis"].strip():
            raise ExperimentError("RESULT.json must contain a non-empty hypothesis.")
        if not isinstance(return_note.get("implementation_summary"), str) or not return_note["implementation_summary"].strip():
            raise ExperimentError("RESULT.json must contain a non-empty implementation_summary.")
    except ExperimentError as exc:
        if not reason:
            reason = f"Agent did not provide a valid RESULT.json: {exc}"

    timeout = int(config["commands"].get("timeout_seconds", 3600))
    evaluation_project = workspace / "evaluation-project"
    evaluation_candidate_file = evaluation_project / editable_files[0]
    if not reason:
        shutil.rmtree(evaluation_project, ignore_errors=True)
        copy_project(project_dir, evaluation_project)
        log_section(f"{name}: build started")
        build_ok = run_command(config["commands"].get("build", []), evaluation_project, evaluation_candidate_file, workspace / "build.log", timeout)
        if not build_ok:
            reason = "Build command failed or timed out."
        else:
            log_section(f"{name}: build finished")

    if not reason:
        result_path = evaluation_project / safe_relative_path(config["evaluation"]["result_file"], "evaluation.result_file")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.unlink(missing_ok=True)
        log_section(f"{name}: evaluation started")
        eval_ok = run_command(config["commands"]["evaluate"], evaluation_project, evaluation_candidate_file, workspace / "evaluation.log", timeout)
        if not eval_ok:
            reason = "Evaluation command failed or timed out."
        else:
            try:
                result, value = validate_evaluation(result_path, config, evaluation_project)
                log_section(f"{name}: evaluation finished")
                approved, reason = approval_decision(
                    value,
                    float((state or {}).get("latest_approved", {}).get("metric", baseline["value"])),
                    config,
                    result["failures"],
                )
            except ExperimentError as exc:
                reason = f"Invalid evaluator result: {exc}"

    log_section(f"{name}: evaluation result and approval decision")
    if result is None:
        unavailable = {
            "status": "unavailable",
            "reason": reason or "No evaluation result was produced.",
        }
        print(json.dumps(unavailable, indent=2), flush=True)
    else:
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    print(f"Approval decision: {'APPROVED' if approved else 'REJECTED'}", flush=True)
    print(f"Approval reason: {reason or 'No approval decision was recorded.'}", flush=True)

    if approved:
        version = version_label(major, minor)
        output = artifact_root / config["workspace"]["approved_dir"] / version
        if output.exists():
            # The completed attempt workspace is authoritative until state
            # commits. Rebuild this version's promotion artifacts after a
            # crash instead of failing on a partial orphan folder.
            shutil.rmtree(output)
        output.mkdir(parents=True)
        approved_project = output / "project"
        copy_project(project_dir, approved_project)
        shutil.copy2(result_path_in_workspace, output / "RESULT.json")
        for filename in ("build.log", "evaluation.log"):
            src = workspace / filename
            if src.exists():
                shutil.copy2(src, output / filename)
        if result is not None:
            shutil.copy2(result_path, output / "evaluation-result.json")
            for artifact_name in result.get("artifacts", []):
                source = evaluation_project / artifact_name
                target = output / "evaluation-artifacts" / artifact_name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        state = state or {}
        state["latest_approved"] = {
            "version": version,
            "project_dir": approved_project.relative_to(config_path.parent).as_posix(),
            "metric": value,
            "metric_name": config["metric"]["name"],
            "direction": config["metric"]["direction"],
        }
    else:
        rejected = (artifact_root / config["workspace"]["rejected_dir"]).resolve() / name
        rejected.parent.mkdir(parents=True, exist_ok=True)
        if rejected.exists():
            rejected = rejected.with_name(f"{name}_{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}")
        shutil.move(str(workspace), str(rejected))
    state = state or {}
    state["next_major"] = major
    state["next_minor"] = minor + 1
    state["configured_major"] = configured_major
    state["seed_dir"] = seed_dir.relative_to(config_path.parent).as_posix()
    atomic_json(state_path, state)
    append_logbook(
        logbook_path,
        name,
        "approved" if approved else "rejected",
        config["metric"]["name"],
        value,
        reason,
        return_note,
        result.get("metrics", {}) if result is not None else {},
        config["metric"]["direction"],
    )
    if approved:
        shutil.rmtree(workspace)
    log_section(f"Experiment {name} complete")
    print(f"{name}: {'APPROVED' if approved else 'REJECTED'} — {reason}", flush=True)
    return name, approved, value, reason


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Sentinel experiment controller.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="TOML experiment configuration.")
    parser.add_argument("--setup-project", action="store_true", help="Create the configured initial V<major>-<minor> project seed folder.")
    parser.add_argument("--prompt", default="", help="Research direction passed to each bounded agent attempt.")
    parser.add_argument("--once", action="store_true", help="Run one attempt and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare one isolated workspace without calling the agent/evaluator.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    try:
        if args.setup_project:
            if args.once or args.dry_run or args.prompt:
                raise ExperimentError("--setup-project cannot be combined with --once, --dry-run, or --prompt.")
            setup_project(config_path)
            return 0
        config = load_config(config_path)
        artifact_root = config_path.parent
        state_path = artifact_root / config["workspace"]["approved_dir"] / "state.json"
        baseline_path = artifact_root / config["workspace"]["approved_dir"] / "baseline.json"
        logbook_path = artifact_root / config["workspace"]["logbook"]
        seed_dir = initial_seed_dir(config, config_path)
        editable_files = [safe_relative_path(item, "candidate.editable_files") for item in config["candidate"]["editable_files"]]
        while True:
            state = load_state(state_path)
            expected_seed = seed_dir.relative_to(artifact_root).as_posix()
            if state and state.get("latest_approved") and not state["latest_approved"].get("project_dir"):
                raise ExperimentError(
                    "Saved state uses the earlier single-file candidate format. Start this setup with a new "
                    "approved_dir or migrate its latest candidate into a full-project seed snapshot."
                )
            if state and state.get("seed_dir") not in (None, expected_seed):
                raise ExperimentError(
                    f"Saved version state belongs to seed {state['seed_dir']}, not {expected_seed}. "
                    "Use a separate approved_dir for each experiment setup."
                )
            active_project = latest_project_dir(state, config, config_path, artifact_root)
            if args.dry_run:
                baseline = {"value": 0.0}
            else:
                saved_baseline = read_json(baseline_path) if baseline_path.exists() else {}
                current_signature = evaluator_signature(config, seed_dir, editable_files)
                if (
                    saved_baseline.get("evaluator_signature") == current_signature
                    and state is not None
                    and state.get("evaluator_signature") == current_signature
                ):
                    baseline = saved_baseline
                else:
                    baseline = establish_baseline(
                        seed_dir,
                        config,
                        config_path,
                        editable_files,
                        baseline_path,
                        artifact_root,
                        state_path,
                        logbook_path,
                        state,
                    )
                    state = load_state(state_path)
            name, _approved, _value, _reason = execute_candidate(
                config,
                config_path,
                seed_dir,
                editable_files,
                state,
                baseline,
                args.prompt,
                args.dry_run,
                artifact_root,
                state_path,
                logbook_path,
            )
            if args.dry_run or args.once:
                return 0
            # A rejected/approved attempt advances persisted state. Setup or
            # baseline errors stop for correction; attempt-level failures are
            # recorded and the controller continues to the next version.
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stop requested; exiting after current operation.", file=sys.stderr)
        return 130
    except ExperimentError as exc:
        print(f"Sentinel: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Sentinel failed unexpectedly: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
