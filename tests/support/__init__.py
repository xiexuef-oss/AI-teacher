"""测试公共支撑：仓库路径与契约加载。"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"
MIGRATIONS_DIR = REPO_ROOT / "migrations"
