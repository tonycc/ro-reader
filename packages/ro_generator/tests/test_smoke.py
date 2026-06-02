"""核心包冒烟测试：验证包可导入。"""

from ro_generator import __version__


def test_version_exists() -> None:
    assert __version__ == "0.0.0"
