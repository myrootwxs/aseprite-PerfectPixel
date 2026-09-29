"""PerfectPixel CLI — Headless command-line bridge for Aseprite and scripts.

Usage example:
    python perfect_pixel_cli.py input.png -o output.png --grid-w 128 --grid-h 128
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

# Ensure stdout and stderr exist even in non-console (GUI) mode
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from perfect_pixel_core import (
    ProcessSettings,
    array_to_png_bytes,
    process_image,
)


def parse_args(args=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PerfectPixel CLI: Reverse-align and refine pixel art into clean grids."
    )
    parser.add_argument("input", help="Path to input image file.")
    parser.add_argument(
        "-o", "--output", required=True, help="Path for output PNG file."
    )

    # Grid settings
    parser.add_argument(
        "--grid-w",
        "--grid-width",
        dest="grid_width",
        type=int,
        default=0,
        help="Target grid width in pixels (0 for auto-detect, default: 0).",
    )
    parser.add_argument(
        "--grid-h",
        "--grid-height",
        dest="grid_height",
        type=int,
        default=0,
        help="Target grid height in pixels (0 for auto-detect, default: 0).",
    )
    parser.add_argument(
        "--sample-method",
        dest="sample_method",
        choices=["center", "majority", "median"],
        default="center",
        help="Sampling strategy inside each cell: center, majority, median.",
    )
    parser.add_argument(
        "--refine-intensity",
        dest="refine_intensity",
        type=float,
        default=0.25,
        help="Edge gradient snap intensity (0.0 to 1.0, default: 0.25).",
    )
    parser.add_argument(
        "--fix-square",
        dest="fix_square",
        action="store_true",
        default=True,
        help="Auto-fix near-square 1px mismatch (default: enabled).",
    )
    parser.add_argument(
        "--no-fix-square",
        dest="fix_square",
        action="store_false",
        help="Disable auto-fix near-square mismatch.",
    )

    # Colors & Quantization
    parser.add_argument(
        "--max-colors",
        dest="max_colors",
        type=int,
        default=0,
        help="Color count ceiling (0 for unlimited, default: 0).",
    )
    parser.add_argument(
        "--color-space",
        dest="color_space",
        choices=["OKLab", "RGB"],
        default="OKLab",
        help="Color perception space for reduction (default: OKLab).",
    )

    # Output scale mode
    parser.add_argument(
        "--scale",
        dest="scale_factor",
        type=int,
        default=1,
        help="Scale factor for output (1 = 1x original pixel grid, >1 = nearest neighbor, default: 1).",
    )

    # Background color removal
    parser.add_argument(
        "--bg-color",
        dest="bg_color",
        default="",
        help="Hex color to treat as background and make transparent (e.g. #ffffff or 'auto').",
    )
    parser.add_argument(
        "--bg-tolerance",
        dest="bg_tolerance",
        type=float,
        default=30.0,
        help="Color distance tolerance for background removal (default: 30.0).",
    )
    parser.add_argument(
        "--bg-mode",
        dest="bg_mode",
        choices=["contiguous", "global"],
        default="contiguous",
        help="Background removal mode: 'contiguous' (flood-fill from outer edges only, default) or 'global'.",
    )
    parser.add_argument(
        "--bg-defringe",
        dest="bg_defringe",
        action="store_true",
        default=True,
        help="Clean anti-aliased edge halos on outline borders (default: enabled).",
    )
    parser.add_argument(
        "--no-bg-defringe",
        dest="bg_defringe",
        action="store_false",
        help="Disable outline defringing.",
    )

    # Cleanup options
    parser.add_argument(
        "--clean-isolated",
        dest="morph_cleanup",
        action="store_true",
        default=False,
        help="Clean isolated single-pixel noise.",
    )
    parser.add_argument(
        "--clean-antialias",
        dest="antialias_cleanup",
        action="store_true",
        default=False,
        help="Clean anti-aliasing color halos around outlines.",
    )
    parser.add_argument(
        "--antialias-threshold",
        dest="antialias_threshold",
        type=float,
        default=30.0,
        help="Threshold for anti-aliasing detection (default: 30.0).",
    )

    # Output format & JSON
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=False,
        help="Print execution result as JSON.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        dest="quiet",
        action="store_true",
        default=False,
        help="Suppress human-readable progress logs.",
    )

    return parser.parse_args(args)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.is_file():
        sys.stderr.write(f"Error: input file does not exist: {input_path}\n")
        return 1

    try:
        with Image.open(input_path) as opened:
            image = ImageOps.exif_transpose(opened)
            image.seek(0)
            mode = (
                "RGBA"
                if "A" in image.getbands() or "transparency" in image.info
                else "RGB"
            )
            converted = image.convert(mode)
            source_array = np.asarray(converted, dtype=np.uint8).copy()
    except Exception as err:
        sys.stderr.write(f"Error reading image {input_path}: {err}\n")
        return 2

    # Map CLI arguments into ProcessSettings
    bg_enabled = bool(args.bg_color)
    bg_color = args.bg_color if args.bg_color else "#ffffff"
    if (
        bg_enabled
        and bg_color.lower().strip() != "auto"
        and not bg_color.startswith("#")
    ):
        bg_color = f"#{bg_color}"

    settings = ProcessSettings(
        sample_method=args.sample_method,
        processing_order="align_first",
        scale_factor=max(1, args.scale_factor),
        max_colors=max(0, args.max_colors),
        color_space=args.color_space,
        grid_width=max(0, args.grid_width),
        grid_height=max(0, args.grid_height),
        refine_intensity=args.refine_intensity,
        fix_square=args.fix_square,
        morph_cleanup=args.morph_cleanup,
        antialias_cleanup=args.antialias_cleanup,
        antialias_threshold=args.antialias_threshold,
        background_enabled=bg_enabled,
        background_color=bg_color,
        background_tolerance=args.bg_tolerance,
        background_transparent=True,
        background_mode=args.bg_mode,
        background_defringe=args.bg_defringe,
    )

    try:
        result = process_image(source_array, settings)
    except Exception as err:
        sys.stderr.write(f"Processing error: {err}\n")
        return 3

    # Output selection: scale=1 uses 1x original grid, scale>1 uses scaled
    out_array = result.original if args.scale_factor <= 1 else result.scaled

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(array_to_png_bytes(out_array))
    except Exception as err:
        sys.stderr.write(f"Error writing output {output_path}: {err}\n")
        return 4

    if args.json_output:
        meta = {
            "status": "success",
            "source_size": [result.source_width, result.source_height],
            "grid_size": [result.grid_width, result.grid_height],
            "output_size": [out_array.shape[1], out_array.shape[0]],
            "scale_factor": result.scale_factor,
            "color_count": result.color_count,
            "has_alpha": result.has_alpha,
            "output_path": str(output_path.resolve()),
        }
        print(json.dumps(meta, ensure_ascii=False))
    elif not args.quiet:
        print(
            f"Success: {result.source_width}x{result.source_height} -> {result.grid_width}x{result.grid_height} "
            f"(Output: {out_array.shape[1]}x{out_array.shape[0]}, {result.color_count} colors) -> {output_path}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
