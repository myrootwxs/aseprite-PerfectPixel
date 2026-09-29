"""Image-processing core for the Perfect Pixel desktop application.

The module deliberately has no UI dependency.  Keeping the processing and
export code separate makes it straightforward to exercise before packaging.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
import zipfile

import cv2
import numpy as np
from PIL import Image
from perfect_pixel import get_perfect_pixel
from perfect_pixel.perfect_pixel import (
    detect_grid_scale,
    refine_grids,
    sample_center,
    sample_majority,
    sample_median,
)


@dataclass(frozen=True)
class ProcessSettings:
    sample_method: str = "center"
    processing_order: str = "align_first"
    scale_factor: int = 8
    max_colors: int = 0
    color_space: str = "OKLab"
    posterize_enabled: bool = False
    posterize_bits: int = 5
    grid_width: int = 0
    grid_height: int = 0
    min_pixel_size: float = 4.0
    peak_width: int = 6
    refine_intensity: float = 0.25
    fix_square: bool = True
    dominant_enabled: bool = False
    dominant_threshold: float = 0.5
    morph_cleanup: bool = False
    antialias_cleanup: bool = False
    antialias_threshold: float = 30.0
    background_enabled: bool = False
    background_color: str = "#ffffff"
    background_tolerance: float = 30.0
    background_transparent: bool = True
    background_mode: str = "contiguous"
    background_defringe: bool = True
    alpha_binarize: bool = False
    alpha_threshold: int = 128


@dataclass(frozen=True)
class ProcessResult:
    original: np.ndarray
    scaled: np.ndarray
    grid_width: int
    grid_height: int
    source_width: int
    source_height: int
    scale_factor: int
    color_count: int
    has_alpha: bool
    settings: ProcessSettings

    @property
    def original_size_text(self) -> str:
        return f"{self.grid_width} × {self.grid_height}"

    @property
    def scaled_size_text(self) -> str:
        return (
            f"{self.grid_width * self.scale_factor} × "
            f"{self.grid_height * self.scale_factor}"
        )

    def report_text(self) -> str:
        sampling = {
            "center": "中心取样",
            "median": "中位数",
            "majority": "多数色",
        }.get(self.settings.sample_method, self.settings.sample_method)
        order = (
            "先对齐，再量化"
            if self.settings.processing_order == "align_first"
            else "先量化，再对齐"
        )
        rows = [
            "Perfect Pixel 处理报告",
            "=" * 28,
            f"原图尺寸：{self.source_width} × {self.source_height}",
            f"像素网格：{self.original_size_text}",
            f"放大尺寸：{self.scaled_size_text} ({self.scale_factor}x)",
            f"实际颜色：{self.color_count} 种",
            f"采样方式：{sampling}",
            f"处理顺序：{order}",
            f"量化空间：{self.settings.color_space}",
            f"透明通道：{'是' if self.has_alpha else '否'}",
        ]
        if self.settings.max_colors:
            rows.append(f"颜色上限：{self.settings.max_colors}")
        if self.settings.posterize_enabled:
            rows.append(f"色阶位数：{self.settings.posterize_bits} bit")
        if self.settings.background_enabled:
            mode_str = (
                "仅外部连通"
                if self.settings.background_mode == "contiguous"
                else "全图相同颜色"
            )
            defringe_str = (
                " + 边缘去杂色" if self.settings.background_defringe else ""
            )
            rows.append(
                f"背景处理：{self.settings.background_color} ({mode_str}{defringe_str}) / "
                f"容差 {self.settings.background_tolerance:g}"
            )
        return "\n".join(rows) + "\n"


def _srgb_to_linear(values: np.ndarray) -> np.ndarray:
    return np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )


def rgb_to_oklab(rgb_u8: np.ndarray) -> np.ndarray:
    rgb = rgb_u8.astype(np.float64) / 255.0
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    lr, lg, lb = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    l = 0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb
    m = 0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb
    s = 0.0883024619 * lr + 0.2164607794 * lg + 0.6652567587 * lb
    l_, m_, s_ = (
        np.cbrt(np.maximum(l, 0)),
        np.cbrt(np.maximum(m, 0)),
        np.cbrt(np.maximum(s, 0)),
    )
    return np.stack(
        [
            0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
        ],
        axis=-1,
    )


def reduce_colors(image: np.ndarray, max_colors: int, color_space: str) -> np.ndarray:
    """Reduce colors with weighted farthest-point palette selection."""
    max_colors = int(max_colors)
    if max_colors <= 0:
        return image

    height, width = image.shape[:2]
    has_alpha = image.shape[2] == 4

    if has_alpha:
        alpha = image[:, :, 3].reshape(-1)
        visible_mask = alpha > 0
        if not np.any(visible_mask):
            return image
        pixels = image[:, :, :3].astype(np.float32).reshape(-1, 3)[visible_mask]
    else:
        visible_mask = None
        pixels = image[:, :, :3].astype(np.float32).reshape(-1, 3)

    unique_rgb, inverse, counts = np.unique(
        pixels, axis=0, return_inverse=True, return_counts=True
    )
    if len(unique_rgb) <= max_colors:
        return image

    if color_space == "OKLab":
        unique_space = rgb_to_oklab(unique_rgb.astype(np.uint8))
    else:
        unique_space = unique_rgb.astype(np.float64)

    weights = counts.astype(np.float64) / counts.sum()
    selected = [int(np.argmax(weights))]
    minimum_distance = np.full(len(unique_rgb), np.inf, dtype=np.float64)
    for _ in range(max_colors - 1):
        distance = np.sum(
            (unique_space - unique_space[selected[-1]]) ** 2, axis=1
        )
        minimum_distance = np.minimum(minimum_distance, distance)
        score = minimum_distance * (1.0 + weights * 5.0)
        score[selected] = -1.0
        selected.append(int(np.argmax(score)))

    palette_rgb = unique_rgb[selected]
    palette_space = unique_space[selected]
    distances = np.sum(
        (unique_space[:, None, :] - palette_space[None, :, :]) ** 2, axis=2
    )
    labels = np.argmin(distances, axis=1)

    if has_alpha and visible_mask is not None:
        result_rgb = image[:, :, :3].copy()
        flat_rgb = result_rgb.reshape(-1, 3)
        flat_rgb[visible_mask] = np.clip(
            np.rint(palette_rgb[labels[inverse]]), 0, 255
        ).astype(np.uint8)
        result = np.concatenate(
            [flat_rgb.reshape(height, width, 3), image[:, :, 3:]], axis=2
        )
    else:
        result = palette_rgb[labels[inverse]].reshape(height, width, 3)
        result = np.clip(np.rint(result), 0, 255).astype(np.uint8)
    return result


def posterize(image: np.ndarray, bits: int) -> np.ndarray:
    bits = int(bits)
    if bits >= 8 or bits < 1:
        return image
    step = 256.0 / (2**bits)
    rgb = image[:, :, :3].astype(np.float32)
    rgb = np.floor(rgb / step) * step + step / 2.0
    result = np.clip(rgb, 0, 255).astype(np.uint8)
    if image.shape[2] == 4:
        return np.concatenate([result, image[:, :, 3:]], axis=2)
    return result


def morphological_cleanup(image: np.ndarray) -> np.ndarray:
    rgb = image[:, :, :3].copy()
    height, width = rgb.shape[:2]
    padded = np.pad(rgb, ((1, 1), (1, 1), (0, 0)), mode="edge")
    up = padded[0:height, 1 : width + 1]
    down = padded[2 : height + 2, 1 : width + 1]
    left = padded[1 : height + 1, 0:width]
    right = padded[1 : height + 1, 2 : width + 2]
    isolated = (
        np.any(rgb != up, axis=2)
        & np.any(rgb != down, axis=2)
        & np.any(rgb != left, axis=2)
        & np.any(rgb != right, axis=2)
    )
    for y, x in zip(*np.where(isolated)):
        neighbours = [up[y, x], down[y, x], left[y, x], right[y, x]]
        best = max(
            neighbours,
            key=lambda candidate: sum(
                np.array_equal(candidate, other) for other in neighbours
            ),
        )
        rgb[y, x] = best
    if image.shape[2] == 4:
        return np.concatenate([rgb, image[:, :, 3:]], axis=2)
    return rgb


def cleanup_antialias(image: np.ndarray, threshold: float) -> np.ndarray:
    rgb = image[:, :, :3].astype(np.float32)
    height, width = rgb.shape[:2]
    padded = np.pad(rgb, ((1, 1), (1, 1), (0, 0)), mode="edge")
    neighbours = [
        padded[1 + dy : height + 1 + dy, 1 + dx : width + 1 + dx]
        for dy in range(-1, 2)
        for dx in range(-1, 2)
        if (dy, dx) != (0, 0)
    ]
    median = np.median(np.stack(neighbours, axis=0), axis=0)
    distance = np.sqrt(np.sum((rgb - median) ** 2, axis=2))
    mask = (distance > 0) & (distance < float(threshold))
    result = image[:, :, :3].copy()
    result[mask] = np.clip(np.rint(median[mask]), 0, 255).astype(np.uint8)
    if image.shape[2] == 4:
        return np.concatenate([result, image[:, :, 3:]], axis=2)
    return result


def _hex_to_rgb(value: str) -> np.ndarray:
    value = value.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        value = "ffffff"
    return np.array(
        [int(value[index : index + 2], 16) for index in (0, 2, 4)],
        dtype=np.uint8,
    )


def detect_background_color(image: np.ndarray) -> np.ndarray:
    """Auto-detect the dominant background color from the image borders and corners."""
    if image is None or image.size == 0:
        return np.array([255, 255, 255], dtype=np.uint8)

    edges = [
        image[0, :, :3],
        image[-1, :, :3],
        image[:, 0, :3],
        image[:, -1, :3],
    ]
    perimeter = np.concatenate(edges, axis=0)
    if image.shape[2] == 4:
        alpha_edges = np.concatenate(
            [image[0, :, 3], image[-1, :, 3], image[:, 0, 3], image[:, -1, 3]]
        )
        visible = alpha_edges > 0
        if np.any(visible):
            perimeter = perimeter[visible]
        else:
            return np.array([255, 255, 255], dtype=np.uint8)

    colors, counts = np.unique(perimeter, axis=0, return_counts=True)
    return colors[np.argmax(counts)]


def remove_background(
    image: np.ndarray,
    color: str | np.ndarray = "#ffffff",
    tolerance: float = 30.0,
    transparent: bool = True,
    mode: str = "contiguous",
    defringe: bool = True,
) -> np.ndarray:
    """Remove background color with optional border-contiguous flood-fill and defringing.

    Parameters
    ----------
    image : np.ndarray
        RGB or RGBA image.
    color : str | np.ndarray
        Hex color ('#ffffff'), 'auto', or RGB uint8 array.
    tolerance : float
        Color distance tolerance (default: 30.0).
    transparent : bool
        Whether to turn removed background pixels transparent (default: True).
    mode : str
        'contiguous' (flood-fill from outer image edges only, protecting interior)
        or 'global' (all matching pixels).
    defringe : bool
        Whether to clean anti-aliasing edge halos on outline borders.
    """
    if isinstance(color, str):
        col_str = color.lower().strip()
        if col_str == "auto" or not col_str:
            bg_rgb = detect_background_color(image)
        else:
            bg_rgb = _hex_to_rgb(color)
    else:
        bg_rgb = np.asarray(color, dtype=np.uint8)[:3]

    bg_float = bg_rgb.astype(np.float32)
    rgb = image[:, :, :3].astype(np.float32)
    dist = np.sqrt(np.sum((rgb - bg_float) ** 2, axis=2))
    raw_mask = dist <= float(tolerance)

    has_alpha = image.shape[2] == 4
    is_transparent = (
        (image[:, :, 3] == 0)
        if has_alpha
        else np.zeros(image.shape[:2], dtype=bool)
    )
    bg_candidate = raw_mask | is_transparent

    if mode == "contiguous":
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            bg_candidate.astype(np.uint8), connectivity=4
        )
        border_labels = np.unique(
            np.concatenate(
                [labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]]
            )
        )
        border_labels = border_labels[border_labels != 0]
        if len(border_labels) > 0:
            bg_mask = np.isin(labels, border_labels)
        else:
            bg_mask = np.zeros(image.shape[:2], dtype=bool)
    else:
        bg_mask = raw_mask

    # Preserve any pre-existing transparent pixels
    bg_mask = bg_mask | is_transparent

    # Defringe: clean 1px anti-aliased edge halo on the boundary between foreground and background
    if defringe and np.any(bg_mask):
        kernel = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], dtype=np.uint8)
        dilated_bg = cv2.dilate(bg_mask.astype(np.uint8), kernel)
        fg_boundary = (dilated_bg > 0) & (~bg_mask)

        # Extended tolerance for boundary fringe
        ext_tol = min(
            150.0, max(float(tolerance) * 2.5, float(tolerance) + 55.0)
        )
        fringe_mask = fg_boundary & (dist <= ext_tol)
        bg_mask = bg_mask | fringe_mask

    if not transparent:
        result = image.copy()
        result[bg_mask, :3] = bg_rgb
        return result

    if has_alpha:
        result = image.copy()
    else:
        result = np.empty((*image.shape[:2], 4), dtype=np.uint8)
        result[:, :, :3] = image[:, :, :3]
        result[:, :, 3] = 255
    result[bg_mask, 3] = 0
    return result


def binarize_alpha(image: np.ndarray, threshold: int) -> np.ndarray:
    if image.shape[2] != 4:
        return image
    result = image.copy()
    result[:, :, 3] = np.where(result[:, :, 3] >= threshold, 255, 0).astype(
        np.uint8
    )
    return result


def sample_dominant(
    image: np.ndarray,
    x_coords: list[int],
    y_coords: list[int],
    threshold: float,
    fallback: str,
) -> np.ndarray:
    height, width = image.shape[:2]
    channels = image.shape[2]
    x_values = np.asarray(x_coords, dtype=np.int32)
    y_values = np.asarray(y_coords, dtype=np.int32)
    output = np.empty(
        (len(y_values) - 1, len(x_values) - 1, channels), dtype=np.uint8
    )
    for row in range(len(y_values) - 1):
        y0 = max(0, int(y_values[row]))
        y1 = min(height, int(y_values[row + 1]))
        if y1 <= y0:
            y1 = min(y0 + 1, height)
        for column in range(len(x_values) - 1):
            x0 = max(0, int(x_values[column]))
            x1 = min(width, int(x_values[column + 1]))
            if x1 <= x0:
                x1 = min(x0 + 1, width)
            cell = image[y0:y1, x0:x1].reshape(-1, channels)
            unique, counts = np.unique(cell, axis=0, return_counts=True)
            dominant = int(np.argmax(counts))
            if counts[dominant] / len(cell) >= threshold:
                output[row, column] = unique[dominant]
            elif fallback == "median":
                output[row, column] = np.clip(
                    np.median(cell.astype(np.float32), axis=0), 0, 255
                ).astype(np.uint8)
            else:
                output[row, column] = image[
                    min((y0 + y1) // 2, height - 1),
                    min((x0 + x1) // 2, width - 1),
                ]
    return output


def _fix_near_square(output: np.ndarray) -> np.ndarray:
    height, width = output.shape[:2]
    if abs(width - height) != 1:
        return output
    if width > height:
        return (
            output[:, :-1]
            if width % 2 == 1
            else np.concatenate([output[:1, :], output], axis=0)
        )
    return (
        output[:-1, :]
        if height % 2 == 1
        else np.concatenate([output[:, :1], output], axis=1)
    )


def _refine_fixed_axis(
    gradient: np.ndarray,
    length: int,
    cell_count: int,
    intensity: float,
) -> list[int]:
    """Refine internal grid lines without ever changing their count."""
    coordinates = [0]
    cell_size = length / cell_count
    search_ratio = max(0.0, min(float(intensity), 1.0))
    for index in range(1, cell_count):
        origin = index * cell_size
        radius = cell_size * search_ratio
        minimum = coordinates[-1] + 1
        # Leave at least one source pixel for every remaining cell.
        maximum = length - (cell_count - index)
        lower = max(minimum, int(np.ceil(origin - radius)))
        upper = min(maximum, int(np.floor(origin + radius)))
        target = int(np.clip(round(origin), minimum, maximum))
        if search_ratio <= 0 or lower > upper:
            coordinates.append(target)
            continue

        positions = np.arange(lower, upper + 1)
        local_gradient = gradient[lower : upper + 1].astype(np.float64)
        peak = max(float(local_gradient.max()), 1.0)
        distance_penalty = peak * 0.12 * np.abs(positions - origin) / max(radius, 1.0)
        best = int(positions[np.argmax(local_gradient - distance_penalty)])
        coordinates.append(best)
    coordinates.append(length)
    return coordinates


def refine_fixed_grid(
    image: np.ndarray,
    grid_width: int,
    grid_height: int,
    intensity: float,
) -> tuple[list[int], list[int]]:
    """Return exactly ``width + 1`` and ``height + 1`` grid boundaries."""
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_RGB2GRAY)
    gradient_x = np.sum(
        np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)), axis=0
    )
    gradient_y = np.sum(
        np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)), axis=1
    )
    return (
        _refine_fixed_axis(gradient_x, width, grid_width, intensity),
        _refine_fixed_axis(gradient_y, height, grid_height, intensity),
    )


def sample_fixed_grid(
    image: np.ndarray,
    x_coords: list[int],
    y_coords: list[int],
    method: str,
) -> np.ndarray:
    if method == "majority":
        return sample_majority(image, x_coords, y_coords)
    if method == "median":
        return sample_median(image, x_coords, y_coords)
    return sample_center(image, x_coords, y_coords)


def process_image(
    source: np.ndarray,
    settings: ProcessSettings,
    progress_callback=None,
) -> ProcessResult:
    """Run the full refinement pipeline and return both output resolutions."""

    def report(percent: int, text: str) -> None:
        if progress_callback:
            progress_callback(percent, text)

    if source is None or source.size == 0:
        raise ValueError("请先选择一张图片。")
    image = np.asarray(source, dtype=np.uint8)
    if image.ndim == 2:
        image = np.stack([image] * 3, axis=-1)
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("无法识别这张图片的颜色格式。")
    source_height, source_width = image.shape[:2]
    rgb = image[:, :, :3]
    if source_width < 2 or source_height < 2:
        raise ValueError("图片尺寸太小，至少需要 2 × 2 像素。")

    report(10, "正在读取颜色与网格…")
    grid_size = None
    if settings.grid_width > 0 or settings.grid_height > 0:
        if settings.grid_width <= 0 or settings.grid_height <= 0:
            raise ValueError("手动网格的宽和高需要同时填写。")
        if (
            settings.grid_width > source_width
            or settings.grid_height > source_height
        ):
            raise ValueError(
                "手动网格不能大于原图尺寸："
                f"当前原图为 {source_width} × {source_height}。"
            )
        grid_size = (settings.grid_width, settings.grid_height)

    working = rgb
    if settings.processing_order == "quantize_first":
        if settings.max_colors > 0:
            working = reduce_colors(
                working, settings.max_colors, settings.color_space
            )
        if settings.posterize_enabled:
            working = posterize(working, settings.posterize_bits)

    report(34, "正在校正像素网格…")
    if grid_size is not None:
        # Manual dimensions are a strict output contract. Internal boundaries
        # may still snap to nearby edges, but their count never changes.
        grid_width, grid_height = grid_size
        x_coords, y_coords = refine_fixed_grid(
            working,
            grid_width,
            grid_height,
            settings.refine_intensity,
        )
        if settings.dominant_enabled:
            output = sample_dominant(
                working,
                x_coords,
                y_coords,
                settings.dominant_threshold,
                settings.sample_method,
            )
        else:
            output = sample_fixed_grid(
                working, x_coords, y_coords, settings.sample_method
            )
    elif settings.dominant_enabled:
        grid_width, grid_height = detect_grid_scale(
            working,
            peak_width=settings.peak_width,
            max_ratio=1.5,
            min_size=settings.min_pixel_size,
        )
        if grid_width is None or grid_height is None:
            raise ValueError("未能识别网格，请尝试手动填写网格宽和高。")
        x_coords, y_coords = refine_grids(
            working, grid_width, grid_height, settings.refine_intensity
        )
        if len(x_coords) < 2 or len(y_coords) < 2:
            raise ValueError("网格线数量不足，请调整网格参数。")
        output = sample_dominant(
            working,
            x_coords,
            y_coords,
            settings.dominant_threshold,
            settings.sample_method,
        )
        if settings.fix_square:
            output = _fix_near_square(output)
        grid_height, grid_width = output.shape[:2]
    else:
        grid_width, grid_height, output = get_perfect_pixel(
            working,
            sample_method=settings.sample_method,
            grid_size=None,
            min_size=settings.min_pixel_size,
            peak_width=settings.peak_width,
            refine_intensity=settings.refine_intensity,
            fix_square=settings.fix_square,
            debug=False,
        )
        if grid_width is None or grid_height is None:
            raise ValueError("未能识别网格，请尝试手动填写网格宽和高。")

    output = output.astype(np.uint8, copy=False)
    report(60, "正在精修颜色与边缘…")

    if settings.background_enabled:
        output = remove_background(
            output,
            settings.background_color,
            settings.background_tolerance,
            settings.background_transparent,
            settings.background_mode,
            settings.background_defringe,
        )

    if settings.processing_order == "align_first":
        if settings.max_colors > 0:
            output = reduce_colors(
                output, settings.max_colors, settings.color_space
            )
        if settings.posterize_enabled:
            output = posterize(output, settings.posterize_bits)
    if settings.morph_cleanup:
        output = morphological_cleanup(output)
    if settings.antialias_cleanup:
        output = cleanup_antialias(output, settings.antialias_threshold)
    if settings.alpha_binarize:
        output = binarize_alpha(output, settings.alpha_threshold)

    grid_height, grid_width = output.shape[:2]
    scale_factor = max(1, int(settings.scale_factor))
    scaled = cv2.resize(
        output,
        (grid_width * scale_factor, grid_height * scale_factor),
        interpolation=cv2.INTER_NEAREST,
    )
    colors = output[:, :, :3].reshape(-1, 3)
    if output.shape[2] == 4:
        visible = output[:, :, 3].reshape(-1) > 0
        colors = colors[visible] if np.any(visible) else colors[:0]
    color_count = len(np.unique(colors, axis=0)) if len(colors) else 0
    report(100, "处理完成")
    return ProcessResult(
        original=output,
        scaled=scaled,
        grid_width=grid_width,
        grid_height=grid_height,
        source_width=source_width,
        source_height=source_height,
        scale_factor=scale_factor,
        color_count=color_count,
        has_alpha=output.shape[2] == 4,
        settings=settings,
    )


def array_to_png_bytes(image: np.ndarray) -> bytes:
    mode = "RGBA" if image.shape[2] == 4 else "RGB"
    buffer = BytesIO()
    Image.fromarray(image, mode=mode).save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def safe_stem(path_or_name: str | Path) -> str:
    stem = Path(path_or_name).stem.strip() or "pixel_art"
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem)
    return stem.rstrip(" .")[:80] or "pixel_art"


def suggested_names(source_name: str | Path, result: ProcessResult) -> dict[str, str]:
    stem = safe_stem(source_name)
    size = f"{result.grid_width}x{result.grid_height}"
    return {
        "original": f"{stem}_perfect_{size}.png",
        "scaled": f"{stem}_perfect_{size}_{result.scale_factor}x.png",
        "zip": f"{stem}_perfect_{size}.zip",
    }


def create_result_zip(result: ProcessResult, source_name: str | Path) -> bytes:
    names = suggested_names(source_name, result)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(names["original"], array_to_png_bytes(result.original))
        archive.writestr(names["scaled"], array_to_png_bytes(result.scaled))
        archive.writestr("处理说明.txt", result.report_text().encode("utf-8-sig"))
    return buffer.getvalue()
