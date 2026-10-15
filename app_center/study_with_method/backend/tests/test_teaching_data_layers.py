from ..teaching_data import load_teaching_data


def test_teaching_data_layers_are_assembled_for_existing_consumers():
    bundle = load_teaching_data()

    assert bundle.manifest["schema_version"] == 2
    canonical = bundle.canonical_knowledge["math.senior-high.function"]
    assert canonical["name"] == "函数的概念与性质"
    assert "questions" not in canonical

    bank = bundle.question_banks["bank.math.xj.required-1.function"]
    assert bank["canonical_knowledge_ids"] == ["math.senior-high.function"]
    assert bank["curriculum_scopes"] == ["xj-math-current"]

    point = bundle.curricula["xj-math-current"]["points"][
        "math.xj.required-1.function"
    ]
    assert point["canonical_id"] == "math.senior-high.function"
    assert point["grade_scope"] == [10]
    assert point["semester_scope"] == "first"
    assert point["question_bank_ids"] == ["bank.math.xj.required-1.function"]
    assert len(point["questions"]) == 5
    assert all(
        question["question_type"] == "single_choice"
        and question["knowledge_point_ids"] == ["math.senior-high.function"]
        and question["cognitive_level"]
        and question["reasoning_steps"] >= 1
        for question in point["questions"]
    )
