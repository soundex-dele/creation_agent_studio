"""Validation helpers for the public input contract of a workflow."""

from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for


SUPPORTED_SCALAR_TYPES = {"string", "number", "integer", "boolean"}
RESERVED_INPUT_KEYS = {"working_directory", "dependency_outputs", "message"}


def validate_workflow_input_schema(schema):
    """Validate the JSON Schema subset rendered by the workflow UI."""

    if not isinstance(schema, dict):
        raise ValueError("input_schema 必须是对象。")
    if not schema:
        return
    if schema.get("type") != "object":
        raise ValueError("input_schema.type 必须是 object。")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError("input_schema.properties 必须是对象。")
    if len(properties) > 50:
        raise ValueError("工作流输入字段不能超过 50 个。")

    for key, definition in properties.items():
        if not isinstance(key, str) or not key or "." in key:
            raise ValueError("工作流输入字段 key 不能为空或包含点号。")
        if key in RESERVED_INPUT_KEYS:
            raise ValueError(f"{key} 是系统保留的工作流输入字段。")
        if not isinstance(definition, dict):
            raise ValueError(f"工作流输入字段 {key} 的定义必须是对象。")
        field_type = definition.get("type")
        if field_type in SUPPORTED_SCALAR_TYPES:
            continue
        if field_type == "array":
            items = definition.get("items")
            if (
                not isinstance(items, dict)
                or items.get("type") != "string"
                or not isinstance(items.get("enum"), list)
            ):
                raise ValueError(
                    f"数组输入字段 {key} 必须提供字符串 enum 选项。"
                )
            continue
        raise ValueError(
            f"工作流输入字段 {key} 使用了不支持的类型：{field_type}。"
        )

    required = schema.get("required", [])
    if (
        not isinstance(required, list)
        or not all(isinstance(key, str) for key in required)
        or len(required) != len(set(required))
    ):
        raise ValueError("input_schema.required 必须是不重复的字段 key 数组。")
    missing = set(required) - set(properties)
    if missing:
        raise ValueError(
            f"必填输入引用了不存在的字段：{', '.join(sorted(missing))}。"
        )
    if schema.get("additionalProperties", False) not in (True, False):
        raise ValueError("input_schema.additionalProperties 必须是布尔值。")

    try:
        validator_type = validator_for(schema)
        validator_type.check_schema(schema)
        for key, definition in properties.items():
            if "default" in definition:
                validator_type(definition).validate(definition["default"])
    except (SchemaError, ValidationError) as exc:
        raise ValueError(f"工作流输入定义无效：{exc.message}") from exc


def workflow_input_properties(schema):
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties")
    return properties if isinstance(properties, dict) else {}
