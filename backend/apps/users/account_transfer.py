"""CSV import/export helpers for administrator-managed accounts."""

import csv
import io

from django.db import transaction

from .models import User
from .serializers import AdminUserSerializer


ACCOUNT_COLUMNS = (
    ("username", "用户名"),
    ("email", "邮箱"),
    ("role", "角色"),
    ("is_active", "允许登录"),
    ("password", "初始密码"),
)

BOOLEAN_FIELDS = {"is_active"}
HEADER_TO_FIELD = {
    alias: key
    for key, label in ACCOUNT_COLUMNS
    for alias in (key, label)
}
ROLE_ALIASES = {
    "平台管理员": User.Role.ADMIN,
    "平台审计员": User.Role.AUDITOR,
    "普通用户": User.Role.MEMBER,
    **{value: value for value, _ in User.Role.choices},
}
TRUE_VALUES = {"1", "true", "yes", "y", "是", "启用", "允许"}
FALSE_VALUES = {"0", "false", "no", "n", "否", "停用", "禁止"}
MAX_IMPORT_ROWS = 1000


class AccountImportError(Exception):
    def __init__(self, detail, errors=None):
        super().__init__(detail)
        self.detail = detail
        self.errors = errors or []


def _csv_text(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[label for _, label in ACCOUNT_COLUMNS],
        lineterminator="\r\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    # A BOM makes Chinese headers open correctly in desktop spreadsheet apps.
    return "\ufeff" + output.getvalue()


def export_accounts_csv(queryset):
    rows = []
    for user in queryset.order_by("id"):
        rows.append({
            "用户名": user.username,
            "邮箱": user.email,
            "角色": user.role,
            "允许登录": "是" if user.is_active else "否",
            "初始密码": "",
        })
    return _csv_text(rows)


def account_import_template_csv():
    return _csv_text([{
        "用户名": "zhangsan",
        "邮箱": "zhangsan@example.com",
        "角色": User.Role.MEMBER,
        "允许登录": "是",
        # Deliberately blank so importing the untouched example cannot create
        # an account with a shared, predictable password.
        "初始密码": "",
    }])


def _decode_upload(upload):
    raw = upload.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AccountImportError("CSV 文件必须使用 UTF-8 编码。") from exc


def _parse_boolean(value, *, row_number, field):
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise AccountImportError(
        "导入文件包含无效数据。",
        [{"row": row_number, "field": field, "messages": ["请填写是/否或 true/false。"]}],
    )


def _normalize_row(source, row_number):
    values = {}
    for header, value in source.items():
        field = HEADER_TO_FIELD.get(str(header or "").strip())
        if not field:
            continue
        value = str(value or "").strip()
        if not value:
            continue
        if field in BOOLEAN_FIELDS:
            values[field] = _parse_boolean(value, row_number=row_number, field=field)
        elif field == "role":
            values[field] = ROLE_ALIASES.get(value, value)
        else:
            values[field] = value
    if values.get("password"):
        values["password_confirm"] = values["password"]
    return values


def _serializer_errors(row_number, errors):
    result = []
    for field, messages in errors.items():
        if isinstance(messages, dict):
            messages = [str(messages)]
        elif not isinstance(messages, (list, tuple)):
            messages = [messages]
        result.append({
            "row": row_number,
            "field": field,
            "messages": [str(message) for message in messages],
        })
    return result


def import_accounts_csv(upload, *, request=None):
    if not upload:
        raise AccountImportError("请选择要导入的 CSV 文件。")
    reader = csv.DictReader(io.StringIO(_decode_upload(upload), newline=""))
    if reader.fieldnames is None:
        raise AccountImportError("CSV 文件缺少表头。")
    recognized = {
        HEADER_TO_FIELD.get(str(header or "").strip())
        for header in reader.fieldnames
    }
    if "username" not in recognized:
        raise AccountImportError("CSV 表头必须包含“用户名”或 username。")

    operations = []
    errors = []
    seen_usernames = set()
    row_count = 0
    for row_number, source in enumerate(reader, start=2):
        if not any(str(value or "").strip() for value in source.values()):
            continue
        row_count += 1
        if row_count > MAX_IMPORT_ROWS:
            raise AccountImportError(f"单次最多导入 {MAX_IMPORT_ROWS} 个账号。")
        try:
            values = _normalize_row(source, row_number)
        except AccountImportError as exc:
            errors.extend(exc.errors)
            continue
        username = values.get("username", "")
        if not username:
            errors.append({
                "row": row_number,
                "field": "username",
                "messages": ["用户名不能为空。"],
            })
            continue
        if username == "system":
            errors.append({
                "row": row_number,
                "field": "username",
                "messages": ["system 是系统保留账号。"],
            })
            continue
        if username in seen_usernames:
            errors.append({
                "row": row_number,
                "field": "username",
                "messages": ["同一文件中用户名不能重复。"],
            })
            continue
        seen_usernames.add(username)
        instance = User.objects.filter(username=username).first()
        serializer = AdminUserSerializer(
            instance,
            data=values,
            partial=instance is not None,
            context={'request': request} if request is not None else {},
        )
        if not serializer.is_valid():
            errors.extend(_serializer_errors(row_number, serializer.errors))
            continue
        operations.append((instance, serializer))

    if not operations and not errors:
        raise AccountImportError("CSV 文件中没有可导入的账号。")
    if errors:
        raise AccountImportError("导入校验失败，未写入任何账号。", errors)

    created = 0
    updated = 0
    with transaction.atomic():
        # Lock the account set and validate the batch's final state as a whole.
        # Per-row validation alone can miss two administrators being downgraded
        # in the same import because each row still sees the other one.
        existing_users = list(User.objects.select_for_update().all())
        touched_ids = {
            instance.pk for instance, _ in operations if instance is not None
        }
        remaining_admins = sum(
            user.pk not in touched_ids
            and user.is_active
            and user.role == User.Role.ADMIN
            for user in existing_users
        )
        resulting_admins = remaining_admins
        for instance, serializer in operations:
            role = serializer.validated_data.get(
                "role", instance.role if instance is not None else User.Role.MEMBER,
            )
            is_active = serializer.validated_data.get(
                "is_active", instance.is_active if instance is not None else True,
            )
            if role == User.Role.ADMIN and is_active:
                resulting_admins += 1
        if resulting_admins < 1:
            raise AccountImportError(
                "导入后系统将没有有效的平台管理员，已取消本次导入。"
            )
        for instance, serializer in operations:
            serializer.save()
            if instance is None:
                created += 1
            else:
                updated += 1
    return {"total": created + updated, "created": created, "updated": updated}
