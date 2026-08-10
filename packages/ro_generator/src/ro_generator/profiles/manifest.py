"""Customer Profile manifest 的共享加载与路径校验。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import yaml

from ro_generator.errors import InvalidProfileError


def load_profile_manifest(root: Path) -> dict[str, object]:
    manifest_path = root / "profile.yaml"
    try:
        with manifest_path.open(encoding="utf-8") as fp:
            raw = yaml.safe_load(fp)
    except OSError as exc:
        raise InvalidProfileError(f"Profile manifest 不可读取：{manifest_path}") from exc
    except yaml.YAMLError as exc:
        raise InvalidProfileError(f"Profile manifest YAML 无法解析：{manifest_path}") from exc
    if not isinstance(raw, dict):
        raise InvalidProfileError(f"Profile manifest 根节点必须是 dict：{manifest_path}")
    return raw


def manifest_string(raw: dict[str, object], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidProfileError(f"Profile manifest 缺少 {key}：{path}")
    return value.strip()


def manifest_relative_path(raw: dict[str, object], key: str, root: Path, path: Path) -> Path:
    value = manifest_string(raw, key, path)
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise InvalidProfileError(f"Profile manifest {key} 必须是 Profile 内相对路径：{path}")
    return root / relative


def manifest_mapping(raw: object, key: str, path: Path) -> Mapping[str, str]:
    if not isinstance(raw, dict):
        raise InvalidProfileError(f"Profile manifest assets.{key} 必须是 dict：{path}")
    parsed: dict[str, str] = {}
    for item_key, item_value in raw.items():
        if not isinstance(item_key, str) or not isinstance(item_value, str):
            raise InvalidProfileError(f"Profile manifest assets.{key} 必须都是字符串：{path}")
        parsed[item_key.strip()] = item_value.strip()
    return MappingProxyType(parsed)


def load_profile_assets(
    root: Path, manifest: dict[str, object]
) -> tuple[
    Path,
    Path,
    Path,
    Mapping[str, str],
    Mapping[str, str],
]:
    """读取并验证 manifest.assets，返回 schema/template/mapping 与目录映射。"""

    manifest_path = root / "profile.yaml"
    assets_raw = manifest.get("assets")
    if not isinstance(assets_raw, dict):
        raise InvalidProfileError(f"Profile manifest 缺少 assets：{manifest_path}")
    schema_path = manifest_relative_path(assets_raw, "schema", root, manifest_path)
    template_root = manifest_relative_path(assets_raw, "template_root", root, manifest_path)
    mapping_root = manifest_relative_path(assets_raw, "mapping_root", root, manifest_path)
    if not schema_path.is_file():
        raise InvalidProfileError(f"Profile schema 文件不存在：{schema_path}")
    if not template_root.is_dir():
        raise InvalidProfileError(f"Profile template 目录不存在：{template_root}")
    if not mapping_root.is_dir():
        raise InvalidProfileError(f"Profile mapping 目录不存在：{mapping_root}")
    seller_directories = manifest_mapping(
        assets_raw.get("seller_directories"), "seller_directories", manifest_path
    )
    mapping_filenames = manifest_mapping(
        assets_raw.get("mapping_filenames"), "mapping_filenames", manifest_path
    )
    return schema_path, template_root, mapping_root, seller_directories, mapping_filenames


__all__ = [
    "load_profile_assets",
    "load_profile_manifest",
    "manifest_mapping",
    "manifest_relative_path",
    "manifest_string",
]
