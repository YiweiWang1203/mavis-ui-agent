from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.ui_element_ontology_evaluator import evaluate_ontology_prediction, format_evaluation_report


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate UI Element Ontology v0.1 prediction JSON against ground truth.")
    parser.add_argument("--ground-truth", required=True, help="Ground truth ontology JSON path")
    parser.add_argument("--prediction", required=True, help="Predicted ontology JSON path")
    parser.add_argument("--iou-threshold", type=float, default=0.5, help="Minimum IoU for bbox matching")
    parser.add_argument("--output-json", help="Optional path to write full evaluation result JSON")
    parser.add_argument("--output-md", help="Optional path to write Markdown report")
    args = parser.parse_args()

    result = evaluate_ontology_prediction(
        _read_json(Path(args.ground_truth)),
        _read_json(Path(args.prediction)),
        iou_threshold=args.iou_threshold,
    )
    report = format_evaluation_report(result)
    print(report)

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
