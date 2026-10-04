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

import io
from pathlib import Path

import numpy as np
from PIL import Image

from lapis_design.render.color import from_oklab
from lapis_design.render.fields.palette import _LINEAR, _lab
from lazuli.ref import study
from lazuli.ref.common import InputError, Profile, cache_folder, fetch, is_url, new_document, page_url

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


def _download(url: str) -> tuple[bytes, str, str]:
    """The picture at `url`, its final address, and its content type. The source registry, robots.txt, and the
    per-host pace apply as for a page (`common.fetch`); a page, not a picture, is for `lazuli ref capture`."""
    _, response = fetch(url)
    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if not kind.startswith("image/"):
        raise InputError(f"{response.url} is {kind or 'of an unknown type'}, not a picture; capture a page with "
                         "`lazuli ref capture`")
    if len(response.body) > study.MAX_IMAGE_BYTES:
        raise InputError(f"{response.url} is {len(response.body):,} bytes, over the {study.MAX_IMAGE_BYTES:,} "
                         "a reference picture may have")
    return response.body, response.url, kind


def profile_image(source: str | Path, rights: str, slug: str) -> Profile:
    """The profile of a local picture, or of the picture at an http(s) address, which is downloaded once."""
    web = is_url(str(source))
    try:
        body, label, content_type = _download(str(source)) if web else (Path(source).read_bytes(), str(source), "")
        with Image.open(io.BytesIO(body)) as image:
            colors = palette(image)
            suffix = study.image_extension(content_type, image.format) if web else Path(source).suffix.lower()
    except OSError as exc:
        raise InputError(f"cannot read the image {source}: {exc}") from exc
    copy = cache_folder(slug) / f"image{suffix}"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(body)
    document = new_document("image", rights)
    document["source"].update({"url": page_url(label)} if web else {"path": str(source)})
    document["image"] = {"path": str(copy), "palette": colors}
    summary = {"colors": len(colors), "largest_share": colors[0]["share"], "image_copy": str(copy)}
    return Profile(document, summary, omitted=list(OMITTED), files={copy.name: copy})
