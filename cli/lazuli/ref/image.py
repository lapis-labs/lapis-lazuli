"""`lazuli ref profile IMAGE`: an image reference's OKLCH palette with area shares.

The palette follows the render palette in render/DERIVED.md, a deterministic k-means: downsample to
at most 256 px wide by area averaging in linear light (weighted by alpha; pixels less than half
covered are left out), convert to OKLab, count pure black and pure white (L <= 0.005 or >= 0.995,
C <= 0.002) as their own `exact` entries, and cluster the rest with k = 8, seeded with the 8 most
frequent colors on a 0.02 OKLab grid (ties by grid coordinates) and iterated until assignments stop
changing, at most 50 rounds. `share` is the share of counted pixels. No `role_guess`: an image has
no page structure to attribute colors to.

A copy of the image goes to the lazuli cache and `image.path` names that copy. `composition` and
`type_impressions` need a vision model and `similar_fonts` a font embedding model; neither is
installed, so they are left out and the report says so.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from lapis_design.render.color import from_oklab
from lapis_design.render.fields.palette import _LINEAR, _lab
from lazuli.ref.common import InputError, Profile, cache_folder, new_document

MAX_WIDTH = 256
CLUSTERS = 8
GRID = .02
MAX_ROUNDS = 50

OMITTED = [
    ("composition", "needs a vision model; none is installed"),
    ("type_impressions", "needs a vision model; none is installed"),
    ("similar_fonts", "needs a font embedding model; none is installed"),
]


def palette(image: Image.Image) -> list[dict]:
    rgba = image.convert("RGBA")
    width = min(MAX_WIDTH, rgba.width)
    height = max(1, round(rgba.height * width / rgba.width))

    def reduce(values: np.ndarray) -> np.ndarray:
        return np.asarray(Image.fromarray(values.astype(np.float32)).resize((width, height), Image.Resampling.BOX))

    alpha = np.asarray(rgba.getchannel("A"), dtype=np.float32) / 255
    coverage = reduce(alpha)
    counted = coverage >= .5
    if not counted.any():
        raise InputError("the image has no opaque pixels to take colors from")
    linear = np.stack([reduce(_LINEAR[np.asarray(rgba.getchannel(band))] * alpha) for band in "RGB"], axis=-1)
    lab = _lab(linear[counted] / coverage[counted][:, None]).astype(np.float64)

    chroma = np.linalg.norm(lab[:, 1:], axis=1)
    white = (lab[:, 0] >= .995) & (chroma <= .002)
    black = (lab[:, 0] <= .005) & (chroma <= .002)
    normal = ~(white | black)
    count = len(lab)
    results = []

    def entry(members: np.ndarray, exact: bool = False) -> None:
        item = {"oklch": from_oklab(*map(float, lab[members].mean(axis=0)), 1),
                "share": round(int(members.sum()) / count, 4)}
        if exact:
            item["exact"] = True
        results.append(item)

    for members in (white, black):
        if members.any():
            entry(members, exact=True)
    if normal.any():
        points = lab[normal]
        bins = np.floor(points / GRID + .5).astype(np.int32)
        quantized, frequency = np.unique(bins, axis=0, return_counts=True)
        order = sorted(range(len(frequency)), key=lambda i: (-frequency[i], *quantized[i]))
        centers = quantized[order[:CLUSTERS]].astype(np.float64) * GRID
        assignments = np.full(len(points), -1)
        for _ in range(MAX_ROUNDS):
            nearest = np.argmin(((points[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2), axis=1)
            if np.array_equal(assignments, nearest):
                break
            assignments = nearest
            for i in range(len(centers)):
                if (nearest == i).any():
                    centers[i] = points[nearest == i].mean(axis=0)
        locations = np.flatnonzero(normal)
        for i in range(len(centers)):
            if (assignments == i).any():
                members = np.zeros(count, dtype=bool)
                members[locations[assignments == i]] = True
                entry(members)
    return sorted(results, key=lambda item: (-item["share"], item["oklch"]))


def profile_image(path: Path, rights: str, slug: str) -> Profile:
    try:
        with Image.open(path) as image:
            colors = palette(image)
    except OSError as exc:
        raise InputError(f"cannot read the image {path}: {exc}") from exc
    copy = cache_folder(slug) / f"image{path.suffix.lower()}"
    copy.parent.mkdir(parents=True, exist_ok=True)
    if copy.resolve() != path.resolve():
        shutil.copyfile(path, copy)
    document = new_document("image", rights)
    document["source"]["path"] = str(path)
    document["image"] = {"path": str(copy), "palette": colors}
    summary = {"colors": len(colors), "largest_share": colors[0]["share"], "image_copy": str(copy)}
    return Profile(document, summary, omitted=list(OMITTED))
