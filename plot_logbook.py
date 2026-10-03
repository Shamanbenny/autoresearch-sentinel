#!/usr/bin/env python3
"""Create dependency-free SVG metric charts from LOGBOOK.json."""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any


DEFAULT_LOGBOOK = Path(__file__).resolve().with_name("LOGBOOK.json")
OUTPUT_PATH = Path(__file__).resolve().with_name("sentinel-research-plot.svg")
MAX_POINTS_PER_PLOT = 50
COLORS = {
    "baseline": "#64748b",
    "approved": "#15803d",
    "rejected": "#dc2626",
    "other": "#2563eb",
}


def numeric_points(document: dict[str, Any], metric: str) -> list[dict[str, Any]]:
    points = []
    for record in document.get("experiments", []):
        if not isinstance(record, dict):
            continue
        raw_value = record.get("metrics", {}).get(metric) if isinstance(record.get("metrics"), dict) else None
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)) or not math.isfinite(raw_value):
            continue
        points.append({
            "candidate": str(record.get("candidate", "unnamed")),
            "status": str(record.get("status", "other")).lower(),
            "value": float(raw_value),
        })
    return points


def svg_chart(metric: str, points: list[dict[str, Any]], direction: str, first_experiment: int) -> str:
    left, right, top, bottom = 90, 35, 75, 150
    width = 1200
    height = 560
    plot_top, plot_bottom = top, height - bottom
    plot_height = plot_bottom - plot_top
    values = [point["value"] for point in points]
    low, high = min(values), max(values)
    padding = (high - low) * 0.12 if high != low else max(abs(low) * 0.08, 1.0)
    low -= padding
    high += padding

    def x_position(index: int) -> float:
        if len(points) == 1:
            return (left + width - right) / 2
        return left + index * (width - left - right) / (len(points) - 1)

    def y_position(value: float) -> float:
        return plot_bottom - (value - low) / (high - low) * plot_height

    title = html.escape(f"Experiment metric: {metric}")
    direction_label = "lower is better" if direction == "minimize" else "higher is better" if direction == "maximize" else "direction unspecified"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="32" text-anchor="middle" font-family="sans-serif" font-size="22" font-weight="bold">{title}</text>',
        f'<text x="{width / 2}" y="55" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#475569">{html.escape(direction_label)}; rejected attempts are included</text>',
    ]

    for tick in range(5):
        value = low + (high - low) * tick / 4
        y = y_position(value)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{left - 12}" y="{y + 4:.1f}" text-anchor="end" font-family="sans-serif" font-size="12" fill="#475569">{value:.5g}</text>')

    coordinates = [(x_position(i), y_position(point["value"])) for i, point in enumerate(points)]
    approved_coordinates = [coordinate for point, coordinate in zip(points, coordinates) if point["status"] == "approved"]
    if len(approved_coordinates) > 1:
        polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in approved_coordinates)
        parts.append(f'<polyline points="{polyline}" fill="none" stroke="#15803d" stroke-width="2"/>')

    for index, (point, (x, y)) in enumerate(zip(points, coordinates)):
        status = point["status"]
        color = COLORS.get(status, COLORS["other"])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{color}" stroke="#ffffff" stroke-width="2"/>')
        if direction == "minimize":
            metric_x, metric_y, metric_anchor = x + 6, y - 12, "middle"
            label_x, label_y, label_anchor, label_angle = x + 6, y - 25, "start", -45
        elif direction == "maximize":
            metric_x, metric_y, metric_anchor = x + 6, y + 20, "start"
            label_x, label_y, label_anchor, label_angle = x + 6, y + 35, "start", 45
        else:
            metric_x, metric_y, metric_anchor = x, y - 12, "middle"
            label_x, label_y, label_anchor, label_angle = x, y - 25, "start", -45
        if status != "rejected":
            parts.append(f'<text x="{metric_x:.1f}" y="{metric_y:.1f}" text-anchor="{metric_anchor}" font-family="sans-serif" font-size="12" fill="#0f172a">{point["value"]:.5g}</text>')
        experiment_number = first_experiment + index
        parts.append(f'<text x="{x:.1f}" y="{plot_bottom + 22}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#334155">{experiment_number}</text>')
        if status == "approved":
            version = point["candidate"].split("_", 1)[0]
            label = html.escape(version)
            parts.append(f'<text transform="translate({label_x:.1f},{label_y:.1f}) rotate({label_angle})" text-anchor="{label_anchor}" font-family="sans-serif" font-size="11" fill="#15803d">{label}</text>')

    parts.append(f'<text x="{(left + width - right) / 2:.1f}" y="{plot_bottom + 78}" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#334155">Experiment #</text>')

    legend_y = height - 24
    legend_x = left
    statuses_present = {point["status"] for point in points}
    for status in ("baseline", "approved", "rejected", "other"):
        if status == "other":
            if not any(item not in COLORS for item in statuses_present):
                continue
        elif status not in statuses_present:
            continue
        label = "other" if status == "other" else status
        color = COLORS[status]
        parts.append(f'<circle cx="{legend_x}" cy="{legend_y - 4}" r="6" fill="{color}"/>')
        parts.append(f'<text x="{legend_x + 11}" y="{legend_y}" font-family="sans-serif" font-size="12" fill="#334155">{label}</text>')
        legend_x += 115

    parts.append(f'<text x="18" y="{plot_top + plot_height / 2}" transform="rotate(-90 18 {plot_top + plot_height / 2})" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#334155">{html.escape(metric)}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot metric trends from the structured experiment logbook.")
    parser.add_argument("--logbook", type=Path, default=DEFAULT_LOGBOOK, help="Path to LOGBOOK.json.")
    parser.add_argument("--metric", help="Metric key to graph; defaults to the only available metric.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Base SVG path; additional pages use -2, -3, and so on.")
    args = parser.parse_args()

    try:
        document = json.loads(args.logbook.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read JSON logbook {args.logbook}: {exc}")
    if not isinstance(document, dict) or not isinstance(document.get("experiments"), list):
        parser.error("logbook must be a JSON object with an experiments array")

    metric_names = sorted({
        key
        for record in document["experiments"] if isinstance(record, dict)
        for key, value in (record.get("metrics", {}).items() if isinstance(record.get("metrics"), dict) else [])
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    })
    if not metric_names:
        parser.error("no numeric metrics found in experiments")
    if args.metric and args.metric not in metric_names:
        parser.error(f"metric not found: {args.metric}")
    if not args.metric and len(metric_names) > 1:
        parser.error(f"select one metric with --metric from: {', '.join(metric_names)}")
    metric = args.metric or metric_names[0]

    project_context = document.get("project_context")
    directions = project_context.get("metric_directions", {}) if isinstance(project_context, dict) else {}
    points = numeric_points(document, metric)
    direction = directions.get(metric, "unspecified") if isinstance(directions, dict) else "unspecified"
    output_paths = []
    for page_start in range(0, len(points), MAX_POINTS_PER_PLOT):
        page_points = points[page_start:page_start + MAX_POINTS_PER_PLOT]
        page_number = page_start // MAX_POINTS_PER_PLOT + 1
        output_path = args.output if page_number == 1 else args.output.with_name(f"{args.output.stem}-{page_number}{args.output.suffix}")
        output_path.write_text(svg_chart(metric, page_points, direction, page_start + 1), encoding="utf-8")
        output_paths.append(output_path)
    print(f"Wrote {len(output_paths)} plot(s) for {len(points)} attempts: {', '.join(map(str, output_paths))}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
