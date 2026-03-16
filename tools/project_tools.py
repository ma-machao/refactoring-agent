from pathlib import Path
from rich.console import Console

from config import IGNORE_DIRS, PYTHON_FILE_SUFFIXES, TEMPLATE_SUFFIXES, REQUIREMENTS_FILES
from tools.fs_tools import find_files_by_name, find_files_by_suffixes, list_all_files, relative_to_root


def discover_python_files(project_root: Path) -> list[str]:
    files = find_files_by_suffixes(project_root, PYTHON_FILE_SUFFIXES, IGNORE_DIRS)
    return [relative_to_root(p, project_root) for p in files]


def discover_template_files(project_root: Path) -> list[str]:
    files = find_files_by_suffixes(project_root, TEMPLATE_SUFFIXES, IGNORE_DIRS)
    return [relative_to_root(p, project_root) for p in files]


def discover_settings_files(project_root: Path) -> list[str]:
    files = find_files_by_name(project_root, "settings.py", IGNORE_DIRS)
    return [relative_to_root(p, project_root) for p in files]


def discover_url_files(project_root: Path) -> list[str]:
    files = find_files_by_name(project_root, "urls.py", IGNORE_DIRS)
    return [relative_to_root(p, project_root) for p in files]


def discover_wsgi_files(project_root: Path) -> list[str]:
    files = find_files_by_name(project_root, "wsgi.py", IGNORE_DIRS)
    return [relative_to_root(p, project_root) for p in files]


def discover_manage_py(project_root: Path) -> list[str]:
    files = find_files_by_name(project_root, "manage.py", IGNORE_DIRS)
    return [relative_to_root(p, project_root) for p in files]


def discover_requirements_files(project_root: Path) -> list[str]:
    all_files = list_all_files(project_root, IGNORE_DIRS)
    matched = [
        p for p in all_files
        if relative_to_root(p, project_root) in REQUIREMENTS_FILES or p.name in REQUIREMENTS_FILES
    ]
    return [relative_to_root(p, project_root) for p in matched]


def discover_template_dirs(project_root: Path) -> list[str]:
    dirs: list[str] = []

    for path in project_root.rglob("templates"):
        if path.is_dir():
            rel = relative_to_root(path, project_root)
            if any(part in IGNORE_DIRS for part in Path(rel).parts):
                continue
            dirs.append(rel)

    return sorted(set(dirs))


def find_module_dir(project_root: Path, module_name: str) -> Path | None:
    candidates: list[Path] = []

    for path in project_root.iterdir():
        if not path.is_dir():
            continue
        if path.name in IGNORE_DIRS:
            continue
        if path.name != module_name:
            continue
        candidates.append(path)

    if not candidates:
        return None

    return candidates[0]


def discover_module_model_files(project_root: Path, module_name: str) -> list[str]:
    module_dir = find_module_dir(project_root, module_name)
    if not module_dir:
        return []

    files: list[Path] = []

    # 1. 优先 models.py
    models_py = module_dir / "models.py"
    if models_py.exists() and models_py.is_file():
        files.append(models_py)

    # 2. 收集模块根目录下其他 .py 文件
    for path in module_dir.glob("*.py"):
        if not path.is_file():
            continue
        if path.name == "__init__.py":
            continue
        rel_parts = path.relative_to(project_root).parts
        if any(part in IGNORE_DIRS for part in rel_parts):
            continue
        files.append(path)

    # 3. 如果有 models/ 目录，也收集进去
    models_dir = module_dir / "models"
    if models_dir.exists() and models_dir.is_dir():
        for path in models_dir.rglob("*.py"):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(project_root).parts
            if any(part in IGNORE_DIRS for part in rel_parts):
                continue
            files.append(path)

    unique = {str(p.resolve()): p for p in files}
    return sorted(relative_to_root(p, project_root) for p in unique.values())


def discover_legacy_modules(project_root: Path) -> list[dict]:
    modules: list[dict] = []

    top_dirs = [p for p in project_root.iterdir() if p.is_dir() and p.name not in IGNORE_DIRS]
    for path in sorted(top_dirs, key=lambda x: x.name):
        name = path.name
        info = classify_legacy_module(project_root, path)
        if info:
            modules.append(info)

    return modules


def classify_legacy_module(project_root: Path, path: Path) -> dict | None:
    name = path.name

    def exists(rel: str) -> bool:
        return (path / rel).exists()

    signals: list[str] = []
    module_type = "generic_module"
    description = "未识别的通用模块"

    if name == "nexus":
        if exists("settings.py"):
            signals.append("settings.py")
        if exists("urls.py"):
            signals.append("urls.py")
        if exists("wsgi.py"):
            signals.append("wsgi.py")

        module_type = "project_config"
        description = "Django project 配置层"
        return {
            "name": name,
            "path": relative_to_root(path, project_root),
            "module_type": module_type,
            "signals": signals,
            "description": description,
        }

    if name == "db":
        if exists("models.py"):
            signals.append("models.py")
        domain_files = [
            "actionlog.py", "apis.py", "auth.py", "cluster.py", "config.py", "consts.py",
            "database.py", "device.py", "direct_link.py", "gpu.py", "ib.py", "image.py",
            "joblistener.py", "jobs.py", "loadbalancer.py", "location.py", "models.py",
            "network.py", "router.py", "schedule.py", "sdn.py", "servers.py",
            "testfixtures.py", "testhelper.py", "tests.py", "volume.py"
        ]
        for f in domain_files:
            if exists(f):
                signals.append(f)

        module_type = "domain_model_layer"
        description = "核心领域模型与数据库相关逻辑层"
        return {
            "name": name,
            "path": relative_to_root(path, project_root),
            "module_type": module_type,
            "signals": signals,
            "description": description,
        }

    if name == "sysadmin":
        if exists("controllers"):
            signals.append("controllers/")
        if exists("forms.py"):
            signals.append("forms.py")
        if exists("urls.py"):
            signals.append("urls.py")
        if exists("views.py"):
            signals.append("views.py")
        if exists("models.py"):
            signals.append("models.py")
        if exists("templatetags"):
            signals.append("templatetags/")

        module_type = "legacy_admin_module"
        description = "旧运维后台 / 管理后台层"
        return {
            "name": name,
            "path": relative_to_root(path, project_root),
            "module_type": module_type,
            "signals": signals,
            "description": description,
        }

    if name == "api":
        if exists("controllers"):
            signals.append("controllers/")
        if exists("urls.py"):
            signals.append("urls.py")
        if exists("views.py"):
            signals.append("views.py")
        if exists("models.py"):
            signals.append("models.py")

        module_type = "legacy_external_api_module"
        description = "旧对外接口层"
        return {
            "name": name,
            "path": relative_to_root(path, project_root),
            "module_type": module_type,
            "signals": signals,
            "description": description,
        }

    if name == "hyperviser":
        service_dirs = ["database", "ebs", "image", "kvm", "loadbalancer", "router", "uplink"]
        for d in service_dirs:
            if exists(d):
                signals.append(f"{d}/")
        if exists("models.py"):
            signals.append("models.py")

        module_type = "infra_service_layer"
        description = "基础设施服务层 / 底层资源操作封装"
        return {
            "name": name,
            "path": relative_to_root(path, project_root),
            "module_type": module_type,
            "signals": signals,
            "description": description,
        }

    if name == "jobd":
        worker_dirs = ["cloudserver", "cluster", "database", "ebs", "image", "network", "report"]
        for d in worker_dirs:
            if exists(d):
                signals.append(f"{d}/")
        if exists("models.py"):
            signals.append("models.py")

        module_type = "job_worker_layer"
        description = "任务调度 / daemon / dispatcher / scheduler 层"
        return {
            "name": name,
            "path": relative_to_root(path, project_root),
            "module_type": module_type,
            "signals": signals,
            "description": description,
        }

    if name == "templates":
        signals.append("global templates/")
        if exists("sysadmin"):
            signals.append("sysadmin/")
        if exists("layout"):
            signals.append("layout/")
        if exists("email"):
            signals.append("email/")

        module_type = "template_layer"
        description = "全局模板层"
        return {
            "name": name,
            "path": relative_to_root(path, project_root),
            "module_type": module_type,
            "signals": signals,
            "description": description,
        }

    # 其他目录也保留，但标成 generic
    py_files = list(path.glob("*.py"))
    if py_files:
        signals.extend(sorted(p.name for p in py_files[:10]))

    return {
        "name": name,
        "path": relative_to_root(path, project_root),
        "module_type": "generic_module",
        "signals": signals,
        "description": "未专门分类的通用目录，可后续再细分",
    }
