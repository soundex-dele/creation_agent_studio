"""Durable Evaluation adapter that executes a frozen target per test case."""

from decimal import Decimal

from django.utils import timezone

from modules.execution.application.runs import create_run
from modules.execution.models import Run
from modules.tenancy.database import tenant_database_context

from .models import EvaluationRun
from .services import evaluate_value


def _actual_value(output):
    if isinstance(output, dict) and "result" in output:
        return output["result"]
    return output


def _score(snapshot, outputs):
    results = []
    evaluators = snapshot.get("evaluators") or [{"type": "exact"}]
    for case in snapshot.get("cases") or []:
        actual = _actual_value(outputs.get(str(case["id"])))
        expected_document = case.get("expected") or {}
        expected = (
            expected_document.get("value", expected_document)
            if isinstance(expected_document, dict)
            else expected_document
        )
        evaluations = [
            evaluate_value(actual, expected, evaluator) for evaluator in evaluators
        ]
        score = sum(item["score"] for item in evaluations) / max(1, len(evaluations))
        results.append(
            {
                "case_id": str(case["id"]),
                "name": case["name"],
                "actual": actual,
                "expected": expected,
                "score": score,
                "passed": all(item["passed"] for item in evaluations),
                "evaluators": evaluations,
            }
        )
    overall = sum(item["score"] for item in results) / max(1, len(results))
    threshold = float((snapshot.get("quality_gate") or {}).get("minimum_score", 1.0))
    return overall, overall >= threshold, results


def execute_evaluation(run_payload, sink):
    snapshot = dict(run_payload.get("definition_snapshot") or {})
    organization_id = run_payload["organization_id"]
    evaluation_run_id = snapshot["evaluation_run_id"]
    with tenant_database_context(organization_id):
        evaluation = EvaluationRun.objects.get(pk=evaluation_run_id)
        EvaluationRun.objects.filter(pk=evaluation.id).update(status="running")
        root = Run.objects.select_related("organization", "owner").get(
            pk=run_payload["run_id"]
        )

        provided_outputs = dict((run_payload.get("input") or {}).get("outputs") or {})
        outputs = dict(provided_outputs)
        target = snapshot.get("target")
        active_ids = []
        if target and not provided_outputs:
            for case in snapshot.get("cases") or []:
                node_key = str(case["id"])
                child = root.child_runs.filter(node_key=node_key).first()
                if child is None:
                    child = create_run(
                        organization=root.organization,
                        owner=root.owner,
                        parent=root,
                        node_key=node_key,
                        executor_kind=target["executor_kind"],
                        executor_key=target["executor_key"],
                        source_type="evaluation_case",
                        source_id=node_key,
                        definition_snapshot=target["definition_snapshot"],
                        input_data=case.get("input") or {},
                        max_attempts=target.get("max_attempts", 3),
                        retry_safe=target.get("retry_safe", True),
                    )
                if child.status == Run.Status.SUCCEEDED:
                    outputs[node_key] = child.output_summary
                elif child.status == Run.Status.WAITING_INPUT:
                    EvaluationRun.objects.filter(pk=evaluation.id).update(
                        status="failed",
                        error=f"Evaluation case {case['name']} requested interactive input.",
                        finished_at=timezone.now(),
                    )
                    raise RuntimeError("Evaluation targets cannot request interactive input")
                elif child.status in (Run.Status.FAILED, Run.Status.CANCELLED):
                    error = child.error_message or child.error_code or child.status
                    EvaluationRun.objects.filter(pk=evaluation.id).update(
                        status="failed", error=error, finished_at=timezone.now()
                    )
                    raise RuntimeError(f"Evaluation case {case['name']} failed: {error}")
                else:
                    active_ids.append(child.id)
        if active_ids:
            sink.wait_for_children(
                child_run_ids=active_ids,
                checkpoint={"evaluation_child_run_ids": [str(value) for value in active_ids]},
            )

        score, passed, results = _score(snapshot, outputs)
        EvaluationRun.objects.filter(pk=evaluation.id).update(
            status="completed",
            score=Decimal(str(score)),
            passed=passed,
            results=results,
            error="",
            finished_at=timezone.now(),
        )
        output = {
            "evaluation_run_id": str(evaluation.id),
            "score": score,
            "passed": passed,
            "results": results,
        }
        sink.emit("output.snapshot", output)
        return output
