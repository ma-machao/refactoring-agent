from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"

DEFAULT_ENCODING = "utf-8"

IGNORE_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pyc",
    ".log",
    ".pid",
    ".swp",
    ".csv",
    ".swo",
    '.py~',
    "build",
    "temp",
    "log",
    ".DS_Store",
    "target",
    "node_modules",
    "dist",
    "build",
    "staticfiles",
    "media",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "venv",
    ".venv",
    "env",
    ".env",
}

PYTHON_FILE_SUFFIXES = {".py"}

TEMPLATE_SUFFIXES = {".html", ".jinja", ".jinja2", ".tpl"}

REQUIREMENTS_FILES = {
    "requirements.txt",
    "requirements-dev.txt",
    "requirements/base.txt",
    "Pipfile",
    "pyproject.toml",
}

TARGET_PROJECT_ROOT = Path("/Users/machao/Desktop/Projects/re-nexus")
