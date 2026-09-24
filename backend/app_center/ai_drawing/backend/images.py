import io
import warnings

from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

MAX_IMAGE_BYTES = 20 * 1024 * 1024
FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def inspect_image(content):
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValidationError("图片大小必须在 1 字节至 20 MB 之间。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in FORMATS or getattr(image, "n_frames", 1) != 1:
                    raise ValidationError("请使用静态 PNG、JPEG 或 WebP 图片。")
                metadata = {"mime_type": FORMATS[image.format], "width": image.width, "height": image.height}
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
        return metadata
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError("图片损坏或像素过大，请更换图片。") from None
