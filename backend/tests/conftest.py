# MirrorTalk - pytest 配置
from __future__ import annotations

import sys
from pathlib import Path

# 让测试能 import app.*
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import pytest
from app.services.database import init_db, get_db


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """"每个测试使用独立临时数据库"""
    from app.config import settings
    db_path = tmp_path / "test_mirrortalk.db"
    chroma_path = tmp_path / "test_chroma"

    monkeypatch.setattr(settings, "sqlite_path", db_path)
    monkeypatch.setattr(settings, "chroma_dir", chroma_path)
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    init_db()
    yield
    # 清理
    try:
        import shutil
        if chroma_path.exists():
            shutil.rmtree(str(chroma_path))
    except Exception:
        pass
