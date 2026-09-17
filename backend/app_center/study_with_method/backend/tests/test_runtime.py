from app_center.study_with_method.runtime import execute_study_with_method


class Sink:
    cancelled = False

    def __init__(self):
        self.events = []

    def emit(self, event_type, payload):
        self.events.append((event_type, payload))


def test_runtime_returns_versioned_math_hint():
    sink = Sink()
    output = execute_study_with_method(
        {
            "input": {
                "operation": "hint",
                "subject": "math",
                "grade_stage": "high_2",
                "problem": "求函数的单调区间",
                "hint_level": 2,
            }
        },
        sink,
    )

    assert output["knowledge_points"] == ["math.function.monotonicity"]
    assert output["hint_level"] == 2
    assert output["validation_status"] == "needs_ai_or_teacher_review"
    assert sink.events == [("output.snapshot", output)]
