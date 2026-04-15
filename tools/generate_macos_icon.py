#!/usr/bin/env python3

"""Generate the macOS app icon assets from a reproducible Python source."""

from __future__ import annotations

import shutil
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError as exc:
    raise SystemExit(
        "Missing Pillow for icon generation. Install it in your system Python and retry."
    ) from exc

ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "assets" / "macos"
ICNS_PATH = ASSETS_DIR / "spotdl-web-downloader.icns"
PREVIEW_PATH = ASSETS_DIR / "spotdl-web-downloader.png"
BASE_SIZE = 1024
BACKGROUND_TOP = (44, 214, 112, 255)
BACKGROUND_BOTTOM = (11, 132, 62, 255)
SURFACE = (10, 24, 34, 255)
WHITE = (255, 255, 255, 255)


def _lerp_channel(start: int, end: int, factor: float) -> int:
    return round(start + (end - start) * factor)


def _vertical_gradient(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)
    for y in range(size):
        factor = y / max(size - 1, 1)
        color = tuple(
            _lerp_channel(BACKGROUND_TOP[index], BACKGROUND_BOTTOM[index], factor)
            for index in range(4)
        )
        draw.line((0, y, size, y), fill=color)
    return image


def _draw_note(draw: ImageDraw.ImageDraw, fill: tuple[int, int, int, int]) -> None:
    draw.rounded_rectangle((332, 300, 408, 700), radius=26, fill=fill)
    draw.rounded_rectangle((620, 218, 696, 600), radius=26, fill=fill)
    draw.polygon(
        ((364, 332), (682, 258), (724, 330), (406, 404)),
        fill=fill,
    )
    draw.ellipse((188, 554, 422, 786), fill=fill)
    draw.ellipse((480, 448, 714, 680), fill=fill)
    draw.polygon(
        ((688, 206), (780, 232), (726, 322), (646, 292)),
        fill=fill,
    )


def build_icon() -> Image.Image:
    """Build the master 1024px icon image."""
    canvas = Image.new("RGBA", (BASE_SIZE, BASE_SIZE), (0, 0, 0, 0))

    shadow = Image.new("RGBA", (BASE_SIZE, BASE_SIZE), (0, 0, 0, 0))
    shadow_mask = ImageDraw.Draw(shadow)
    shadow_mask.rounded_rectangle(
        (52, 70, 972, 990),
        radius=236,
        fill=(0, 0, 0, 84),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    canvas.alpha_composite(shadow)

    rounded_mask = Image.new("L", (BASE_SIZE, BASE_SIZE), 0)
    ImageDraw.Draw(rounded_mask).rounded_rectangle(
        (40, 40, 984, 984),
        radius=220,
        fill=255,
    )
    canvas.alpha_composite(
        Image.composite(
            _vertical_gradient(BASE_SIZE),
            Image.new("RGBA", (BASE_SIZE, BASE_SIZE)),
            rounded_mask,
        )
    )

    overlays = Image.new("RGBA", (BASE_SIZE, BASE_SIZE), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlays)
    overlay_draw.ellipse((152, 150, 872, 870), fill=(8, 23, 33, 48))
    overlay_draw.ellipse((176, 176, 848, 848), outline=(255, 255, 255, 36), width=18)
    overlay_draw.ellipse((108, 96, 446, 434), fill=(255, 255, 255, 18))
    canvas.alpha_composite(overlays)

    note_shadow = Image.new("RGBA", (BASE_SIZE, BASE_SIZE), (0, 0, 0, 0))
    _draw_note(ImageDraw.Draw(note_shadow), (5, 18, 25, 110))
    note_shadow = note_shadow.filter(ImageFilter.GaussianBlur(26))
    canvas.alpha_composite(note_shadow)

    notes = Image.new("RGBA", (BASE_SIZE, BASE_SIZE), (0, 0, 0, 0))
    _draw_note(ImageDraw.Draw(notes), WHITE)
    canvas.alpha_composite(notes)

    accent = Image.new("RGBA", (BASE_SIZE, BASE_SIZE), (0, 0, 0, 0))
    accent_draw = ImageDraw.Draw(accent)
    accent_draw.arc(
        (170, 170, 850, 850), start=212, end=315, fill=(255, 255, 255, 58), width=20
    )
    canvas.alpha_composite(accent)
    return canvas


def save_assets(master_icon: Image.Image) -> None:
    """Write the preview PNG and final `.icns` app icon."""
    legacy_iconset_dir = ASSETS_DIR / "spotdl-web-downloader.iconset"
    if legacy_iconset_dir.exists():
        shutil.rmtree(legacy_iconset_dir)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    master_icon.save(PREVIEW_PATH)
    master_icon.save(
        ICNS_PATH,
        sizes=[
            (16, 16),
            (32, 32),
            (64, 64),
            (128, 128),
            (256, 256),
            (512, 512),
            (1024, 1024),
        ],
    )


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    master_icon = build_icon()
    save_assets(master_icon)
    print(f"Generated {ICNS_PATH}")


if __name__ == "__main__":
    main()
