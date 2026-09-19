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
    catalog_validator = Draft202012Validator(_read_schema(root, "catalog.schema.json"))
    point_validator = Draft202012Validator(_read_schema(root, "knowledge-point.schema.json"))
    manifest = _read_yaml(root / "manifest.yaml")
    if str(manifest.get("data_version")) != data_version:
        raise TeachingDataError("教学数据版本在读取过程中发生变化，请重试。")
    curricula = {}
    global_point_ids = set()
    for entry in manifest.get("curricula") or []:
        catalog_path = root / entry["catalog"]
        catalog = _read_yaml(catalog_path)
        _validate(catalog_validator, catalog, str(catalog_path))
        points = {}
        for filename in sorted(glob.glob(str(root / entry["knowledge_glob"]))):
            path = Path(filename)
            point = _read_yaml(path)
            _validate(point_validator, point, str(path))
            point_id = point["id"]
            if point_id in global_point_ids:
                raise TeachingDataError(f"知识点 ID 重复：{point_id}")
            global_point_ids.add(point_id)
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
    return TeachingDataBundle(manifest=manifest, curricula=curricula)


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
                                        "name": points[point_id]["name"],
                                        "summary": points[point_id]["summary"],
                                        "objectives": points[point_id]["objectives"],
                                        "prerequisites": points[point_id]["prerequisites"],
                                        "common_mistakes": points[point_id]["common_mistakes"],
                                        "keywords": points[point_id]["keywords"],
                                        "competency_tags": points[point_id]["competency_tags"],
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
                                        "summary": point["summary"],
                                        "keywords": point["keywords"],
                                        "data_version": bundle.manifest["data_version"],
                                    },
                                },
                            )
                            changed += int(created)
    return changed
