"""列对应关系修复校验码。

界面不提供设置入口。默认码随发版内置；本机可用配置文件覆盖，改文件即可生效，不必重新发版。
这是软管控：拦住工作台界面，不对抗直接改 YAML。
"""

from __future__ import annotations

from pathlib import Path

SCHEMA_PIN_FILENAME = "schema_pin.txt"
# 配置文件不存在或无效时的内置默认码。
SCHEMA_REPAIR_PIN = "RO8601"

_PIN_FILE_HEADER = (
    "# 列对应关系修复校验码。改此文件即可，不必重新发版；下次输入时生效。\n"
    "# 第一行非空、非 # 注释的内容即为校验码。界面里不能改这个文件。\n"
)


def schema_pin_path(config_dir: str | Path) -> Path:
    return Path(config_dir) / SCHEMA_PIN_FILENAME


def ensure_schema_pin_file(config_dir: str | Path) -> Path:
    """配置目录里没有校验码文件时写入默认文件，方便授权人员直接改。"""

    path = schema_pin_path(config_dir)
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{_PIN_FILE_HEADER}{SCHEMA_REPAIR_PIN}\n", encoding="utf-8")
    except OSError:
        pass
    return path


def load_schema_pin(config_dir: str | Path) -> str:
    """读取本机配置文件中的校验码；缺失或无效时回退到内置默认。"""

    path = schema_pin_path(config_dir)
    try:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    return stripped
    except OSError:
        pass
    return SCHEMA_REPAIR_PIN


def verify_schema_pin(pin: str, *, config_dir: str | Path) -> bool:
    """比对用户输入与当前生效的校验码（配置文件优先）。"""

    if not isinstance(pin, str) or not pin.strip():
        return False
    return pin.strip() == load_schema_pin(config_dir)
