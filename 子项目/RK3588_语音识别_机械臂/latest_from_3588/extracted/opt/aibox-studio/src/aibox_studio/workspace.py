from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .course import Experiment


class WorkspaceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.experiments_path = self.root / "experiments"
        self.backups_path = self.root / "backups"

    def load(self, experiment: Experiment) -> str:
        path = self._path(experiment)
        if not path.exists():
            return experiment.template_code
        return path.read_text(encoding="utf-8")

    def save(self, experiment: Experiment, code: str) -> Path:
        self.experiments_path.mkdir(parents=True, exist_ok=True)
        path = self._path(experiment)
        path.write_text(code, encoding="utf-8")
        return path

    def reset(self, experiment: Experiment) -> str:
        path = self._path(experiment)
        if path.exists():
            self.backups_path.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = self.backups_path / f"{experiment.id}-{stamp}.py"
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        self.save(experiment, experiment.template_code)
        return experiment.template_code

    def _path(self, experiment: Experiment) -> Path:
        return self.experiments_path / f"{experiment.id}.py"

