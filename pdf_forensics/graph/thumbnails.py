"""
Thumbnail generation for graph node tooltips.
"""

import base64


THUMBNAIL_MAX_SIZE = 200
THUMBNAIL_MAX_BYTES = 500 * 1024  # 500 KB


def make_thumbnail_data_uri(image_bytes, ext, width, height):
    """
    Convert image bytes to a base64 data URI, resizing if needed.

    Returns (data_uri, displayed_width, displayed_height) or None
    if the image can't be processed.
    """
    if not image_bytes:
        return None

    # If image is small enough and common format, embed as-is
    if (len(image_bytes) <= THUMBNAIL_MAX_BYTES
            and width and height
            and max(width, height) <= THUMBNAIL_MAX_SIZE):
        mime = f"image/{ext}" if ext in ("jpeg", "jpg", "png",
                                          "gif", "webp") else None
        if mime:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            return (f"data:{mime};base64,{b64}", width, height)

    # Otherwise resize via Pillow
    try:
        from PIL import Image
        import io
    except ImportError:
        return None

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception:
        return None

    # Convert mode if needed for JPEG output
    if img.mode in ("RGBA", "LA", "P"):
        if img.mode == "P":
            img = img.convert("RGBA")
        # Preserve transparency by outputting PNG
        output_format = "PNG"
        mime = "image/png"
    else:
        output_format = "JPEG"
        mime = "image/jpeg"

    # Resize preserving aspect ratio
    orig_w, orig_h = img.size
    max_edge = max(orig_w, orig_h)
    if max_edge > THUMBNAIL_MAX_SIZE:
        scale = THUMBNAIL_MAX_SIZE / max_edge
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
    else:
        new_w, new_h = orig_w, orig_h

    buf = io.BytesIO()
    save_kwargs = {"optimize": True}
    if output_format == "JPEG":
        save_kwargs["quality"] = 80
    img.save(buf, format=output_format, **save_kwargs)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return (f"data:{mime};base64,{b64}", new_w, new_h)
