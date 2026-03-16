from pathlib import Path
from pydantic import BaseModel, Field

from tools.project_tools import (
    discover_legacy_modules,
    discover_manage_py,
    discover_python_files,
    discover_requirements_files,
    discover_settings_files,
    discover_template_dirs,
    discover_template_files,
    discover_url_files,
    discover_wsgi_files,
)


class LegacyModuleInfo(BaseModel):
    name: str
    path: str
    module_type: str
    signals: list[str] = Field(default_factory=list)
    description: str = ""


class ProjectScanResult(BaseModel):
    project_root: str
    total_python_files: int = 0
    total_template_files: int = 0

    manage_files: list[str] = Field(default_factory=list)
    settings_files: list[str] = Field(default_factory=list)
    url_files: list[str] = Field(default_factory=list)
    wsgi_files: list[str] = Field(default_factory=list)
    requirements_files: list[str] = Field(default_factory=list)
    template_dirs: list[str] = Field(default_factory=list)

    legacy_modules: list[LegacyModuleInfo] = Field(default_factory=list)
    python_files_sample: list[str] = Field(default_factory=list)
    template_files_sample: list[str] = Field(default_factory=list)


class ProjectScanner:
    def scan(self, project_root: Path) -> ProjectScanResult:
        python_files = discover_python_files(project_root)
        template_files = discover_template_files(project_root)
        legacy_modules = discover_legacy_modules(project_root)

        return ProjectScanResult(
            project_root=str(project_root),
            total_python_files=len(python_files),
            total_template_files=len(template_files),
            manage_files=discover_manage_py(project_root),
            settings_files=discover_settings_files(project_root),
            url_files=discover_url_files(project_root),
            wsgi_files=discover_wsgi_files(project_root),
            requirements_files=discover_requirements_files(project_root),
            template_dirs=discover_template_dirs(project_root),
            legacy_modules=[LegacyModuleInfo(**item) for item in legacy_modules],
            python_files_sample=python_files[:50],
            template_files_sample=template_files[:50],
        )
