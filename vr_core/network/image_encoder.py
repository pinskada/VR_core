"""Image encoder for packing multiple images into a single byte payload."""

from typing import Iterable, Tuple, Literal, List
import struct

import cv2
import numpy as np


# ---- Protocol constants  ----
# FrameHeader: 1 byte (image count)
# EyeHeader:   [EyeID:1][Width:2][Height:2][ImageSize:4]  ==> 9 bytes total
# Endianness:  Little-endian to match C# BitConverter.ToUInt16/ToInt32 on little-endian platforms.
# EyeID:       0 = left, 1 = right (as per your C# comment)
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB max per image

Codec = Literal["jpeg", "png"]

def encode_images_packet(
    items: Iterable[Tuple[int, np.ndarray]],
    *,
    codec: Codec = "jpeg",
    jpeg_quality: int = 85,
    png_compression: int = 3,
    color_is_bgr: bool = True,
) -> bytes:
    """
    Pack multiple images into one message for Unity's ImageDecoder.

    Args:
        items: iterable of (eye_id, image ndarray). eye_id: 0 (left) or 1 (right).
               image: HxWxC uint8 array (grayscale or BGR/RGB) or HxW uint8.
        codec: "jpeg" or "png".
        jpeg_quality: 0..100 (higher = better quality, larger).
        png_compression: 0..9   (higher = smaller, slower).
        color_is_bgr: If True, treat 3-channel images as BGR (OpenCV default). If False, RGB.

    Returns:
        bytes: payload formatted as:
               [count:1][for each image -> EyeID:1, W:2, H:2, Size:4, Data:Size]
    """
    # Collect (eye_id, (w,h), encoded_bytes) first to know sizes
    prepared: List[Tuple[int, Tuple[int, int], bytes]] = []

    # Normalize and encode
    for eye_id, img in items:
        if not isinstance(eye_id, int) or not 0 <= eye_id <= 255:
            raise ValueError(f"EyeID must fit in 1 byte (0..255). Got: {eye_id}")
        if img is None:
            raise ValueError("Image is None.")

        # Ensure uint8 or bool format
        if img.dtype == np.bool_:
            img = img.astype(np.uint8) * 255  # True→255, False→0
        elif img.dtype != np.uint8:
            raise ValueError(f"Unsupported dtype: {img.dtype}")

        # Determine width/height and channel handling
        if img.ndim == 2:
            h, w = img.shape
            img_to_encode = img
        elif img.ndim == 3 and img.shape[2] in (3, 4):
            h, w, c = img.shape
            img_to_encode = img

            # Drop alpha if present
            if c == 4:
                img_to_encode = img_to_encode[:, :, :3]

            # OpenCV expects BGR. If given RGB, convert.
            if not color_is_bgr:
                img_to_encode = cv2.cvtColor(img_to_encode, cv2.COLOR_RGB2BGR)
        else:
            raise ValueError(f"Unsupported image shape: {img.shape}")

        # Encode
        if codec.lower() == "jpeg":
            # JPEG cannot be true 1-bit; if your input is binary, still fine as 8-bit.
            encode_ok, buf = cv2.imencode(
                ".jpg",
                img_to_encode,
                [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)]
            )
        elif codec.lower() == "png":
            encode_ok, buf = cv2.imencode(
                ".png",
                img_to_encode,
                [int(cv2.IMWRITE_PNG_COMPRESSION), int(png_compression)]
            )
        else:
            raise ValueError("codec must be 'jpeg' or 'png'")

        if not encode_ok:
            raise RuntimeError("cv2.imencode failed")

        data = buf.tobytes()
        size = len(data)
        if size <= 0:
            raise RuntimeError("Encoded image is empty")
        if size > MAX_IMAGE_SIZE:
            raise ValueError(f"Encoded image size {size} exceeds limit {MAX_IMAGE_SIZE}")

        prepared.append((eye_id, (w, h), data))

    count = len(prepared)
    if not 0 <= count <= 255:
        raise ValueError(f"Image count must fit in 1 byte (0..255). Got: {count}")

    # Build payload
    parts = [struct.pack("<B", count)]  # FrameHeader: number of images (1 byte)
    for eye_id, (w, h), data in prepared:
        header = struct.pack("<BHHI", eye_id, w & 0xFFFF, h & 0xFFFF, len(data) & 0xFFFFFFFF)
        parts.append(header)
        parts.append(data)

    return b"".join(parts)
