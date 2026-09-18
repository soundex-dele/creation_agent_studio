"""Reusable attachment persistence for durable conversation starters."""

import hashlib
import mimetypes
import uuid
from pathlib import Path

from PIL import Image
from rest_framework.exceptions import ValidationError

from .models import MessageAttachment


def prepare_image_specs(images):
    """Read stable image metadata once before transaction retries begin."""

    specs = []
    for image in images or ():
        image.seek(0)
        checksum = hashlib.sha256()
        for chunk in image.chunks():
            checksum.update(chunk)
        image.seek(0)
        dimensions = getattr(getattr(image, "image", None), "size", (None, None))
        specs.append({
            "id": uuid.uuid4(),
            "file": image,
            "original_name": str(image.name or "image")[:255],
            "content_type": str(image.content_type),
            "byte_size": image.size,
            "width": dimensions[0],
            "height": dimensions[1],
            "checksum_sha256": checksum.hexdigest(),
        })
    return specs


def persist_message_attachments(*, message, conversation, specs, saved_storage_names):
    """Persist validated uploads and return JSON-safe Codex attachment input."""

    runtime_attachments = []
    for spec in specs:
        attachment = MessageAttachment(
            id=spec["id"],
            organization=conversation.organization,
            conversation=conversation,
            message=message,
            original_name=spec["original_name"],
            content_type=spec["content_type"],
            byte_size=spec["byte_size"],
            width=spec["width"],
            height=spec["height"],
            checksum_sha256=spec["checksum_sha256"],
        )
        spec["file"].seek(0)
        attachment.file.save(spec["original_name"], spec["file"], save=False)
        saved_storage_names.append(attachment.file.name)
        attachment.save()
        try:
            local_path = attachment.file.path
        except NotImplementedError as exc:
            raise ValidationError({
                "images": "Codex 图片输入要求使用可访问的本地文件存储。",
            }) from exc
        runtime_attachments.append({
            "id": str(attachment.id),
            "name": attachment.original_name,
            "content_type": attachment.content_type,
            "byte_size": attachment.byte_size,
            "path": str(local_path),
        })
    return runtime_attachments


def attach_existing_image(*, message, conversation, image_field):
    """Attach an already persisted local image without duplicating its storage blob."""

    image_field.open("rb")
    try:
        checksum = hashlib.sha256()
        for chunk in image_field.chunks():
            checksum.update(chunk)
        image_field.seek(0)
        with Image.open(image_field) as image:
            width, height = image.size
        image_field.seek(0)
        content_type = mimetypes.guess_type(image_field.name)[0] or "image/jpeg"
        attachment = MessageAttachment(
            organization=conversation.organization,
            conversation=conversation,
            message=message,
            original_name=Path(image_field.name).name[:255],
            content_type=content_type,
            byte_size=image_field.size,
            width=width,
            height=height,
            checksum_sha256=checksum.hexdigest(),
        )
        attachment.file.name = image_field.name
        attachment.save()
        try:
            local_path = attachment.file.path
        except NotImplementedError as exc:
            raise ValidationError({
                "images": "Codex 图片输入要求使用可访问的本地文件存储。",
            }) from exc
        return attachment, {
            "id": str(attachment.id),
            "name": attachment.original_name,
            "content_type": attachment.content_type,
            "byte_size": attachment.byte_size,
            "path": str(local_path),
        }
    finally:
        image_field.close()
