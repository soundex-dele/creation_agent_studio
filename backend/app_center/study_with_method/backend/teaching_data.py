from __future__ import annotations

import glob
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from django.conf import settings
from jsonschema import Draft202012Validator

from .models import CurriculumNode, GradeStage


class TeachingDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class TeachingDataBundle:
    manifest: dict
    canonical_knowledge: dict[str, dict]
    question_banks: dict[str, dict]
    curricula: dict[str, dict]


def _read_yaml(path: Path):
    try:
        with path.open(encoding="utf-8") as stream:
            return yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise TeachingDataError(f"无法读取教学数据 {path}: {exc}") from exc


def _read_schema(root: Path, name: str):
    try:
        return json.loads((root / "schemas" / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TeachingDataError(f"无法读取教学数据 Schema {name}: {exc}") from exc


def _validate(validator, value, label: str):
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.path)
        raise TeachingDataError(f"{label} 校验失败 {location}: {first.message}")


@lru_cache(maxsize=8)
def _load_bundle(root_value: str, data_version: str) -> TeachingDataBundle:
    root = Path(root_value)
    manifest_validator = Draft202012Validator(
        _read_schema(root, "manifest.schema.json")
    )
    catalog_validator = Draft202012Validator(_read_schema(root, "catalog.schema.json"))
    knowledge_validator = Draft202012Validator(
        _read_schema(root, "canonical-knowledge.schema.json")
    )
    mapping_validator = Draft202012Validator(
        _read_schema(root, "curriculum-mapping.schema.json")
    )
    bank_validator = Draft202012Validator(
        _read_schema(root, "question-bank.schema.json")
    )
    manifest = _read_yaml(root / "manifest.yaml")
    _validate(manifest_validator, manifest, str(root / "manifest.yaml"))
    if str(manifest.get("data_version")) != data_version:
        raise TeachingDataError("教学数据版本在读取过程中发生变化，请重试。")
    canonical_knowledge = {}
    for domain in manifest.get("knowledge_domains") or []:
        filenames = sorted(
            glob.glob(str(root / domain["knowledge_glob"]), recursive=True)
        )
        if not filenames:
            raise TeachingDataError(
                f"通用知识目录未匹配到文件：{domain['knowledge_glob']}"
            )
        for filename in filenames:
            path = Path(filename)
            point = _read_yaml(path)
            _validate(knowledge_validator, point, str(path))
            point_id = point["id"]
            if point_id in canonical_knowledge:
                raise TeachingDataError(f"通用知识点 ID 重复：{point_id}")
            if point["subject"] != domain["subject"]:
                raise TeachingDataError(f"通用知识点学科与目录不一致：{point_id}")
            if point["education_stage"] != domain["education_stage"]:
                raise TeachingDataError(f"通用知识点学段与目录不一致：{point_id}")
            canonical_knowledge[point_id] = point

    question_banks = {}
    global_question_ids = set()
    for bank_entry in manifest.get("question_banks") or []:
        filenames = sorted(
            glob.glob(str(root / bank_entry["question_glob"]), recursive=True)
        )
        if not filenames:
            raise TeachingDataError(
                f"题库目录未匹配到文件：{bank_entry['question_glob']}"
            )
        for filename in filenames:
            path = Path(filename)
            bank = _read_yaml(path)
            _validate(bank_validator, bank, str(path))
            bank_id = bank["id"]
            if bank_id in question_banks:
                raise TeachingDataError(f"题库 ID 重复：{bank_id}")
            if bank["subject"] != bank_entry["subject"]:
                raise TeachingDataError(f"题库学科与目录不一致：{bank_id}")
            if bank["education_stage"] != bank_entry["education_stage"]:
                raise TeachingDataError(f"题库学段与目录不一致：{bank_id}")
            missing = set(bank["canonical_knowledge_ids"]) - set(canonical_knowledge)
            if missing:
                raise TeachingDataError(f"题库引用了不存在的通用知识点：{sorted(missing)}")
            for question in bank["questions"]:
                if question["id"] in global_question_ids:
                    raise TeachingDataError(f"题目 ID 重复：{question['id']}")
                global_question_ids.add(question["id"])
            question_banks[bank_id] = bank

    curricula = {}
    global_mapping_ids = set()
    for entry in manifest.get("curricula") or []:
        catalog_path = root / entry["catalog"]
        catalog = _read_yaml(catalog_path)
        _validate(catalog_validator, catalog, str(catalog_path))
        points = {}
        filenames = sorted(
            glob.glob(str(root / entry["knowledge_mapping_glob"]), recursive=True)
        )
        if not filenames:
            raise TeachingDataError(
                f"教材映射目录未匹配到文件：{entry['knowledge_mapping_glob']}"
            )
        for filename in filenames:
            path = Path(filename)
            mapping = _read_yaml(path)
            _validate(mapping_validator, mapping, str(path))
            point_id = mapping["id"]
            if point_id in global_mapping_ids:
                raise TeachingDataError(f"教材知识点映射 ID 重复：{point_id}")
            global_mapping_ids.add(point_id)
            if mapping["curriculum_id"] != entry["id"]:
                raise TeachingDataError(f"教材知识点映射版本不一致：{point_id}")
            if mapping["subject"] != entry["subject"]:
                raise TeachingDataError(f"教材知识点映射学科不一致：{point_id}")
            canonical = canonical_knowledge.get(mapping["canonical_id"])
            if canonical is None:
                raise TeachingDataError(
                    f"教材知识点映射引用不存在：{mapping['canonical_id']}"
                )
            if canonical["subject"] != mapping["subject"]:
                raise TeachingDataError(f"教材知识点映射与通用知识点学科不一致：{point_id}")
            questions = []
            for bank_id in mapping["question_bank_ids"]:
                bank = question_banks.get(bank_id)
                if bank is None:
                    raise TeachingDataError(f"教材知识点映射引用的题库不存在：{bank_id}")
                if entry["id"] not in bank["curriculum_scopes"]:
                    raise TeachingDataError(f"题库不适用于教材版本：{bank_id}")
                if mapping["canonical_id"] not in bank["canonical_knowledge_ids"]:
                    raise TeachingDataError(f"题库不适用于通用知识点：{bank_id}")
                if mapping["education_stage"] != bank["education_stage"]:
                    raise TeachingDataError(f"题库与教材映射学段不一致：{bank_id}")
                if not set(mapping["grade_scope"]).issubset(set(bank["grade_scope"])):
                    raise TeachingDataError(f"题库未覆盖教材映射年级：{bank_id}")
                questions.extend(bank["questions"])
            point = {
                **canonical,
                "id": point_id,
                "canonical_id": canonical["id"],
                "curriculum_id": mapping["curriculum_id"],
                "name": mapping["display_name"],
                "grade_scope": mapping["grade_scope"],
                "semester_scope": mapping["semester_scope"],
                "reference": mapping["reference"],
                "question_bank_ids": mapping["question_bank_ids"],
                "questions": questions,
            }
            points[point_id] = point
        referenced = {
            point_id
            for volume in catalog["volumes"]
            for chapter in volume["chapters"]
            for section in chapter["sections"]
            for point_id in section["knowledge_points"]
        }
        if referenced != set(points):
            missing = sorted(referenced - set(points))
            extra = sorted(set(points) - referenced)
            raise TeachingDataError(
                f"{entry['id']} 目录引用不完整，缺失={missing}，未引用={extra}"
            )
        curricula[entry["id"]] = {
            "meta": entry,
            "catalog": catalog,
            "points": points,
        }
    return TeachingDataBundle(
        manifest=manifest,
        canonical_knowledge=canonical_knowledge,
        question_banks=question_banks,
        curricula=curricula,
    )


def load_teaching_data() -> TeachingDataBundle:
    root = Path(settings.TEACHING_DATA_ROOT)
    manifest = _read_yaml(root / "manifest.yaml")
    data_version = str(manifest.get("data_version") or "")
    if not data_version:
        raise TeachingDataError("教学数据 manifest 缺少 data_version。")
    return _load_bundle(str(root), data_version)


def curriculum_entry(*, subject: str, curriculum_id: str) -> dict:
    bundle = load_teaching_data()
    entry = bundle.curricula.get(curriculum_id)
    if entry is None or entry["meta"]["subject"] != subject:
        raise ValueError("学科与教材版本不匹配。")
    return entry


def public_curriculum_tree(*, subject: str, curriculum_id: str) -> dict:
    entry = curriculum_entry(subject=subject, curriculum_id=curriculum_id)
    points = entry["points"]
    catalog = entry["catalog"]
    return {
        "id": curriculum_id,
        "subject": subject,
        "label": entry["meta"]["label"],
        "publisher": entry["meta"]["publisher"],
        "volumes": [
            {
                **volume,
                "chapters": [
                    {
                        **chapter,
                        "sections": [
                            {
                                **section,
                                "knowledge_points": [
                                    {
                                        "id": point_id,
                                        "canonical_id": points[point_id]["canonical_id"],
                                        "name": points[point_id]["name"],
                                        "education_stage": points[point_id]["education_stage"],
                                        "grade_scope": points[point_id]["grade_scope"],
                                        "semester_scope": points[point_id]["semester_scope"],
                                        "summary": points[point_id]["summary"],
                                        "objectives": points[point_id]["objectives"],
                                        "prerequisites": points[point_id]["prerequisites"],
                                        "common_mistakes": points[point_id]["common_mistakes"],
                                        "keywords": points[point_id]["keywords"],
                                        "competency_tags": points[point_id]["competency_tags"],
                                        "knowledge_items": points[point_id]["knowledge_items"],
                                    }
                                    for point_id in section["knowledge_points"]
                                ],
                            }
                            for section in chapter["sections"]
                        ],
                    }
                    for chapter in volume["chapters"]
                ],
            }
            for volume in catalog["volumes"]
        ],
    }


def get_knowledge_point(*, subject: str, curriculum_id: str, code: str) -> dict:
    entry = curriculum_entry(subject=subject, curriculum_id=curriculum_id)
    point = entry["points"].get(code)
    if point is None:
        raise ValueError("知识点不存在或不属于所选教材。")
    return point


def sync_curriculum_nodes() -> int:
    bundle = load_teaching_data()
    changed = 0
    for curriculum_id, entry in bundle.curricula.items():
        subject = entry["meta"]["subject"]
        points = entry["points"]
        for grade_stage in GradeStage.values:
            for volume_order, volume in enumerate(entry["catalog"]["volumes"], 1):
                volume_node, created = CurriculumNode.objects.update_or_create(
                    subject=subject,
                    grade_stage=grade_stage,
                    curriculum_version=curriculum_id,
                    code=volume["id"],
                    defaults={
                        "name": volume["name"],
                        "node_type": CurriculumNode.NodeType.VOLUME,
                        "parent": None,
                        "order": volume_order,
                        "metadata": {"active": True, "label": entry["meta"]["label"]},
                    },
                )
                changed += int(created)
                for chapter_order, chapter in enumerate(volume["chapters"], 1):
                    chapter_node, created = CurriculumNode.objects.update_or_create(
                        subject=subject,
                        grade_stage=grade_stage,
                        curriculum_version=curriculum_id,
                        code=chapter["id"],
                        defaults={
                            "name": chapter["name"],
                            "node_type": CurriculumNode.NodeType.CHAPTER,
                            "parent": volume_node,
                            "order": chapter_order,
                            "metadata": {"active": True},
                        },
                    )
                    changed += int(created)
                    for section_order, section in enumerate(chapter["sections"], 1):
                        section_node, created = CurriculumNode.objects.update_or_create(
                            subject=subject,
                            grade_stage=grade_stage,
                            curriculum_version=curriculum_id,
                            code=section["id"],
                            defaults={
                                "name": section["name"],
                                "node_type": CurriculumNode.NodeType.SECTION,
                                "parent": chapter_node,
                                "order": section_order,
                                "metadata": {"active": True},
                            },
                        )
                        changed += int(created)
                        for point_order, point_id in enumerate(section["knowledge_points"], 1):
                            point = points[point_id]
                            _, created = CurriculumNode.objects.update_or_create(
                                subject=subject,
                                grade_stage=grade_stage,
                                curriculum_version=curriculum_id,
                                code=point_id,
                                defaults={
                                    "name": point["name"],
                                    "node_type": CurriculumNode.NodeType.KNOWLEDGE_POINT,
                                    "parent": section_node,
                                    "order": point_order,
                                    "metadata": {
                                        "active": True,
                                        "canonical_id": point["canonical_id"],
                                        "education_stage": point["education_stage"],
                                        "grade_scope": point["grade_scope"],
                                        "semester_scope": point["semester_scope"],
                                        "question_bank_ids": point["question_bank_ids"],
                                        "summary": point["summary"],
                                        "keywords": point["keywords"],
                                        "knowledge_items": point["knowledge_items"],
                                        "data_version": bundle.manifest["data_version"],
                                    },
                                },
                            )
                            changed += int(created)
    return changed
