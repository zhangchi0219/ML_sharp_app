"""Application image adapter shared by thumbnails and SHARP inference."""
from __future__ import annotations

import math
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()


def decode_image(source: Path | BinaryIO) -> tuple[Image.Image, float]:
    with Image.open(source) as original:
        exif = dict(original.getexif())
        exif.update(original.getexif().get_ifd(0x8769))
        focal = exif.get(41989)
        if not focal or float(focal) < 1:
            focal = float(exif.get(37386) or 30)
            if focal < 10:
                focal *= 8.4
        focal = float(focal)
        if not math.isfinite(focal) or focal <= 0:
            focal = 30.0
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.load()
        return image, focal


def load_rgb(path: Path):
    image, focal = decode_image(path)
    f_px = focal * math.hypot(*image.size) / math.hypot(36, 24)
    return np.asarray(image), image.info.get("icc_profile"), f_px
