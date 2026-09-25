"""Build the Lotus theme art: the starfield with faded rifles, plus the spinnable Lotus head.

The heads are not baked in: the page places them as elements (LOTUS_MARKS in
team_scout_html.py) so a double-click can spin them.

Sources live in Graphics/ (not tracked). Run from the repo root:
    python scout/assets/build_lotus_background.py
"""

import os

from PIL import Image, ImageEnhance, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STARS = os.path.join(ROOT, "Graphics", "Huge night sky XL.jpg")
# The source is 8480x6360; scale it down only this far so the pinprick stars survive.
FIELD_SIZE = (2560, 1920)
RIFLE = os.path.join(ROOT, "Graphics", "ak47.png")
OUT = os.path.join(ROOT, "scout", "assets", "lotus_starfield.jpg")
HEAD = os.path.join(ROOT, "Graphics", "Lotus.png")
HEAD_OUT = os.path.join(ROOT, "scout", "assets", "lotus_mark.png")
HEAD_WIDTH = 320
GLOW_COLOR = (92, 200, 255)
# Shrinks every rifle in PLACEMENTS by the same factor without re-laying them out.
RIFLE_SCALE = 0.85

# (center x, center y, width px, rotation deg, mirrored, opacity, blur px) laid out on a 1920x1280
# grid and scaled to FIELD_SIZE when composited.
PLACEMENTS = [
    # Scattered through the side margins so nothing sits behind the stats panels in the
    # middle. Deliberately uneven: mixed sizes, angles, depths and distances from the edge.
    (60, 120, 210, 38, False, 0.72, 0.6),
    (225, 340, 280, -24, True, 0.80, 0.0),
    (110, 610, 190, 104, False, 0.62, 0.9),
    (245, 870, 230, 16, False, 0.74, 0.3),
    (70, 1080, 260, -52, True, 0.80, 0.0),
    (230, 1235, 170, 170, True, 0.60, 0.9),
    (1660, 95, 190, -8, True, 0.66, 0.8),
    (1840, 300, 250, 58, False, 0.80, 0.0),
    (1705, 575, 220, -31, False, 0.82, 0.0),
    (1875, 810, 180, 128, True, 0.60, 1.0),
    (1690, 1000, 220, 12, True, 0.72, 0.4),
    (1835, 1195, 240, -70, False, 0.78, 0.0),
]


def load_cutout(path):
    image = Image.open(path).convert("RGBA")
    return image.crop(image.getchannel("A").getbbox())


def space_tint(image, color=0.6, brightness=1.7, blue_mix=0.18):
    """Pull the image toward the starfield's cold blue so it sits in the scene.

    Rifles are brightened well past the source: gunmetal and walnut are nearly black,
    and on a near-black sky an untouched rifle barely separates from the background.
    """
    rgb = ImageEnhance.Color(image.convert("RGB")).enhance(color)
    rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
    blue = Image.new("RGB", rgb.size, (90, 140, 200))
    rgb = Image.blend(rgb, blue, blue_mix)
    tinted = rgb.convert("RGBA")
    tinted.putalpha(image.getchannel("A"))
    return tinted


def with_glow(piece, radius):
    """Faint cool edge glow so the silhouette reads against empty space."""
    pad = radius * 3
    canvas = Image.new("RGBA", (piece.width + pad * 2, piece.height + pad * 2), (0, 0, 0, 0))
    canvas.paste(piece, (pad, pad))
    halo = canvas.getchannel("A").filter(ImageFilter.GaussianBlur(radius)).point(lambda a: round(a * 0.45))
    glow = Image.new("RGBA", canvas.size, GLOW_COLOR)
    glow.putalpha(halo)
    glow.alpha_composite(canvas)
    return glow


def build():
    Image.MAX_IMAGE_PIXELS = None  # the source sky is ~54 megapixels
    field = Image.open(STARS).convert("RGB").resize(FIELD_SIZE, Image.Resampling.LANCZOS).convert("RGBA")
    sx, sy = FIELD_SIZE[0] / 1920, FIELD_SIZE[1] / 1280
    rifle = space_tint(load_cutout(RIFLE))
    for cx, cy, width, angle, mirrored, opacity, blur in PLACEMENTS:
        cx, cy, width = round(cx * sx), round(cy * sy), round(width * sx * RIFLE_SCALE)
        piece = rifle.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirrored else rifle
        piece = piece.resize((width, round(piece.height * width / piece.width)), Image.Resampling.LANCZOS)
        piece = piece.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        piece = with_glow(piece, round(5 * sx))
        if blur:
            piece = piece.filter(ImageFilter.GaussianBlur(blur))
        piece.putalpha(piece.getchannel("A").point(lambda a: round(a * opacity)))
        layer = Image.new("RGBA", field.size, (0, 0, 0, 0))
        layer.paste(piece, (cx - piece.width // 2, cy - piece.height // 2))
        field.alpha_composite(layer)
    field.convert("RGB").save(OUT, "JPEG", quality=78, optimize=True, progressive=True)
    return OUT


def build_head():
    head = load_cutout(HEAD)
    head = head.resize((HEAD_WIDTH, round(head.height * HEAD_WIDTH / head.width)), Image.Resampling.LANCZOS)
    # A face is already bright, so only a light cool tint, no brightening.
    head = with_glow(space_tint(head, color=0.85, brightness=1.0, blue_mix=0.1), 6)
    head.save(HEAD_OUT, "PNG", optimize=True)
    return HEAD_OUT


if __name__ == "__main__":
    print(build())
    print(build_head())
