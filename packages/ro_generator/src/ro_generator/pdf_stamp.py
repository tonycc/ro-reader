"""Invoice/PL PDF 主体印章：LibreOffice 转换后再叠图，Excel 导出不受影响。"""

from __future__ import annotations

import zlib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import MappingProxyType

import yaml
from PIL import Image
from pypdf import PdfReader, PdfWriter

from ro_generator.resources import resource_root

POINTS_PER_CM = 72.0 / 2.54
_STAMPABLE_DOCUMENTS = frozenset({"INVOICE", "PL"})
_DEFAULT_MARGIN_RIGHT_CM = 1.2
_DEFAULT_MARGIN_BOTTOM_CM = 1.5
_PAPER_THRESHOLD = 240


@dataclass(frozen=True)
class SellerStamp:
    path: Path
    width_cm: float
    height_cm: float


@dataclass(frozen=True)
class StampCatalog:
    documents: frozenset[str]
    margin_right_cm: float
    margin_bottom_cm: float
    sellers: Mapping[str, SellerStamp]


def default_stamps_root() -> Path:
    return resource_root() / "customer_profiles" / "stamps"


def stamp_box_pt(
    *,
    page_width_pt: float,
    page_height_pt: float,
    width_cm: float,
    height_cm: float,
    margin_right_cm: float,
    margin_bottom_cm: float,
) -> tuple[float, float, float, float]:
    del page_height_pt
    width = width_cm * POINTS_PER_CM
    height = height_cm * POINTS_PER_CM
    x = page_width_pt - width - margin_right_cm * POINTS_PER_CM
    y = margin_bottom_cm * POINTS_PER_CM
    return x, y, width, height


def seller_stamp_box_pt(
    page_width_pt: float,
    page_height_pt: float,
    catalog: StampCatalog,
    seller: str,
) -> tuple[float, float, float, float] | None:
    stamp = catalog.sellers.get(seller)
    if stamp is None:
        return None
    return stamp_box_pt(
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
        width_cm=stamp.width_cm,
        height_cm=stamp.height_cm,
        margin_right_cm=catalog.margin_right_cm,
        margin_bottom_cm=catalog.margin_bottom_cm,
    )


def load_stamp_spec(stamps_root: Path | None = None) -> StampCatalog | None:
    root = stamps_root if stamps_root is not None else default_stamps_root()
    yaml_path = root / "stamps.yaml"
    if not yaml_path.is_file():
        return None
    try:
        with yaml_path.open(encoding="utf-8") as fp:
            raw = yaml.safe_load(fp)
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict):
        return None
    documents = {
        str(item) for item in raw.get("documents", ()) if isinstance(item, str) and item.strip()
    }
    sellers_raw = raw.get("sellers")
    if not isinstance(sellers_raw, dict):
        return None
    sellers: dict[str, SellerStamp] = {}
    for seller, spec in sellers_raw.items():
        stamp = _seller_stamp_from_raw(root, seller, spec)
        if stamp is not None:
            sellers[str(seller)] = stamp
    if not sellers:
        return None
    return StampCatalog(
        documents=frozenset(documents or _STAMPABLE_DOCUMENTS),
        margin_right_cm=_float_or_default(raw.get("margin_right_cm"), _DEFAULT_MARGIN_RIGHT_CM),
        margin_bottom_cm=_float_or_default(raw.get("margin_bottom_cm"), _DEFAULT_MARGIN_BOTTOM_CM),
        sellers=MappingProxyType(sellers),
    )


def apply_seller_stamp(
    pdf_path: Path,
    *,
    seller: str,
    document_types: Collection[str],
    stamps_root: Path | None = None,
) -> None:
    """把主体印章叠到 PDF 每一页右下角。缺配置/缺文件/非 Invoice·PL 时原样返回。"""

    catalog = load_stamp_spec(stamps_root)
    if catalog is None:
        return
    if not _STAMPABLE_DOCUMENTS.intersection(document_types):
        return
    if not catalog.documents.intersection(document_types):
        return
    stamp = catalog.sellers.get(seller)
    if stamp is None or not stamp.path.is_file():
        return
    try:
        _overlay_stamp(pdf_path, stamp, catalog)
    except Exception:
        return


def _seller_stamp_from_raw(root: Path, seller: object, spec: object) -> SellerStamp | None:
    del seller
    if not isinstance(spec, dict):
        return None
    filename = spec.get("file")
    if not isinstance(filename, str) or not filename.strip():
        return None
    relative = Path(filename.strip())
    if relative.is_absolute() or ".." in relative.parts:
        return None
    path = root / relative
    shape = str(spec.get("shape", "")).strip()
    if shape == "circle":
        diameter = _float_or_default(spec.get("diameter_cm"), 0)
        if diameter <= 0:
            return None
        return SellerStamp(path=path, width_cm=diameter, height_cm=diameter)
    width = _float_or_default(spec.get("width_cm"), 0)
    height = _float_or_default(spec.get("height_cm"), 0)
    if width <= 0 or height <= 0:
        return None
    return SellerStamp(path=path, width_cm=width, height_cm=height)


def _float_or_default(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _overlay_stamp(pdf_path: Path, stamp: SellerStamp, catalog: StampCatalog) -> None:
    image = _knockout_paper(Image.open(stamp.path))
    writer = PdfWriter(clone_from=pdf_path)
    for page in writer.pages:
        mediabox = page.mediabox
        x, y, width, height = stamp_box_pt(
            page_width_pt=float(mediabox.width),
            page_height_pt=float(mediabox.height),
            width_cm=stamp.width_cm,
            height_cm=stamp.height_cm,
            margin_right_cm=catalog.margin_right_cm,
            margin_bottom_cm=catalog.margin_bottom_cm,
        )
        overlay = PdfReader(
            BytesIO(
                _stamp_overlay_pdf(
                    image,
                    page_width_pt=float(mediabox.width),
                    page_height_pt=float(mediabox.height),
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                )
            )
        )
        page.merge_page(overlay.pages[0], over=True)

    tmp_path = pdf_path.with_name(f"{pdf_path.stem}.stamped.pdf")
    try:
        writer.write(tmp_path)
        tmp_path.replace(pdf_path)
    finally:
        if tmp_path.exists() and tmp_path != pdf_path:
            tmp_path.unlink(missing_ok=True)


def _knockout_paper(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = bytearray(rgba.tobytes())
    for offset in range(0, len(pixels), 4):
        red, green, blue = pixels[offset], pixels[offset + 1], pixels[offset + 2]
        if (red >= _PAPER_THRESHOLD and green >= _PAPER_THRESHOLD and blue >= _PAPER_THRESHOLD) or (
            min(red, green, blue) >= 220 and max(red, green, blue) - min(red, green, blue) < 12
        ):
            pixels[offset + 3] = 0
    knocked = Image.frombytes("RGBA", rgba.size, bytes(pixels))
    bbox = knocked.getbbox()
    return knocked.crop(bbox) if bbox else knocked


def _stamp_overlay_pdf(
    image: Image.Image,
    *,
    page_width_pt: float,
    page_height_pt: float,
    x: float,
    y: float,
    width: float,
    height: float,
) -> bytes:
    rgba = image.convert("RGBA")
    red, green, blue, alpha = rgba.split()
    rgb_stream = zlib.compress(Image.merge("RGB", (red, green, blue)).tobytes())
    mask_stream = zlib.compress(alpha.tobytes())
    content = f"q {width:.4f} 0 0 {height:.4f} {x:.4f} {y:.4f} cm /RoStmp Do Q\n".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width_pt:.4f} {page_height_pt:.4f}] "
            "/Resources << /XObject << /RoStmp 4 0 R >> >> /Contents 6 0 R >>"
        ).encode("ascii"),
        _image_stream_object(
            rgb_stream,
            width=rgba.width,
            height=rgba.height,
            color_space=b"/DeviceRGB",
            extra=b" /SMask 5 0 R",
        ),
        _image_stream_object(
            mask_stream,
            width=rgba.width,
            height=rgba.height,
            color_space=b"/DeviceGray",
        ),
        _stream_object(content),
    ]
    return _pdf_from_objects(objects)


def _image_stream_object(
    data: bytes,
    *,
    width: int,
    height: int,
    color_space: bytes,
    extra: bytes = b"",
) -> bytes:
    header = (
        b"<< /Type /XObject /Subtype /Image /Width "
        + str(width).encode("ascii")
        + b" /Height "
        + str(height).encode("ascii")
        + b" /ColorSpace "
        + color_space
        + b" /BitsPerComponent 8 /Filter /FlateDecode"
        + extra
        + b" /Length "
        + str(len(data)).encode("ascii")
        + b" >>"
    )
    return header + b"\nstream\n" + data + b"\nendstream"


def _stream_object(data: bytes) -> bytes:
    header = b"<< /Length " + str(len(data)).encode("ascii") + b" >>"
    return header + b"\nstream\n" + data + b"\nendstream"


def _pdf_from_objects(bodies: list[bytes]) -> bytes:
    parts: list[bytes] = [b"%PDF-1.4\n"]
    offsets: list[int] = []
    for index, body in enumerate(bodies, start=1):
        offsets.append(sum(len(part) for part in parts))
        parts.append(str(index).encode("ascii") + b" 0 obj\n" + body + b"\nendobj\n")
    xref_at = sum(len(part) for part in parts)
    xref = [f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f \n".encode("ascii")]
    xref.extend(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets)
    trailer = (
        f"trailer << /Size {len(bodies) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return b"".join(parts) + b"".join(xref) + trailer
