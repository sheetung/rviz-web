"""
pytest 配置文件
"""

import pytest

from app.core.config import get_settings


@pytest.fixture
def settings():
    """获取测试设置"""
    return get_settings()
