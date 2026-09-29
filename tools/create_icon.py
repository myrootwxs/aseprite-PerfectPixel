"""Generate the application PNG and multi-resolution Windows icon."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

SCALE = 4
SIZE = 256
canvas = Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE), (0, 0, 0, 0))
draw = ImageDraw.Draw(canvas)

dark = "#0B1014"
surface = "#121B21"
line = "#294047"
accent = "#42D7C2"

margin = 12 * SCALE
draw.rounded_rectangle(
    (margin, margin, SIZE * SCALE - margin, SIZE * SCALE - margin),
    radius=52 * SCALE,
    fill=dark,
)
draw.rounded_rectangle(
    (30 * SCALE, 30 * SCALE, 226 * SCALE, 226 * SCALE),
    radius=35 * SCALE,
    fill=surface,
    outline=line,
    width=3 * SCALE,
)

gap = 10 * SCALE
cell = 62 * SCALE
left = 61 * SCALE
top = 61 * SCALE
for row in range(2):
    for column in range(2):
        x0 = left + column * (cell + gap)
        y0 = top + row * (cell + gap)
        color = accent if row == column else line
        draw.rounded_rectangle(
            (x0, y0, x0 + cell, y0 + cell),
            radius=10 * SCALE,
            fill=color,
        )

shine = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
shine_draw = ImageDraw.Draw(shine)
shine_draw.polygon(
    [(35 * SCALE, 55 * SCALE), (150 * SCALE, 30 * SCALE), (55 * SCALE, 150 * SCALE)],
    fill=(255, 255, 255, 12),
)
canvas = Image.alpha_composite(canvas, shine)
canvas = canvas.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
canvas.save(ASSETS / "perfect_pixel.png", optimize=True)
canvas.save(
    ASSETS / "perfect_pixel.ico",
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
