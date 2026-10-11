from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


class CourseValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Experiment:
    id: str
    number: int
    title: str
    description: str
    template_code: str
    allowed_imports: tuple[str, ...]
    capabilities: tuple[str, ...]
    resources: tuple[str, ...]
    panel: str
    run_mode: str
    timeout_seconds: float
    output_limit_bytes: int


@dataclass(frozen=True)
class Chapter:
    id: str
    title: str
    experiments: tuple[Experiment, ...]


@dataclass(frozen=True)
class CoursePart:
    id: str
    title: str
    chapters: tuple[Chapter, ...]


class CourseCatalog:
    def __init__(self, *, title: str, parts: tuple[CoursePart, ...]):
        self.title = title
        self.parts = parts
        self.experiments = tuple(
            experiment
            for part in parts
            for chapter in part.chapters
            for experiment in chapter.experiments
        )
        self._by_id = {experiment.id: experiment for experiment in self.experiments}

    def experiment(self, experiment_id: str) -> Experiment:
        try:
            return self._by_id[experiment_id]
        except KeyError as error:
            raise CourseValidationError(f"未知实验ID：{experiment_id}") from error

    @classmethod
    def load(cls, root: str | Path) -> CourseCatalog:
        root = Path(root).resolve()
        manifest = cls._read_json(root / "manifest.json")
        entry_path = cls._inside(root, manifest.get("entry", ""), "课程入口路径")
        content = cls._read_json(entry_path)
        seen_ids: set[str] = set()
        parts: list[CoursePart] = []

        for part_data in sorted(content.get("parts", []), key=lambda item: item.get("order", 0)):
            chapters: list[Chapter] = []
            for chapter_data in sorted(part_data.get("chapters", []), key=lambda item: item.get("order", 0)):
                experiments: list[Experiment] = []
                for item in chapter_data.get("experiments", []):
                    experiment_id = str(item.get("id", ""))
                    if experiment_id in seen_ids:
                        raise CourseValidationError(f"实验ID重复：{experiment_id}")
                    seen_ids.add(experiment_id)
                    template_path = cls._inside(root, item.get("template", ""), "模板路径")
                    experiments.append(
                        Experiment(
                            id=experiment_id,
                            number=int(item["number"]),
                            title=str(item["title"]),
                            description=str(item.get("description", "")),
                            template_code=template_path.read_text(encoding="utf-8"),
                            allowed_imports=tuple(item.get("allowed_imports", ())),
                            capabilities=tuple(item.get("capabilities", ())),
                            resources=tuple(item.get("resources", ())),
                            panel=str(item.get("panel", "text")),
                            run_mode=str(item.get("run_mode", "oneshot")),
                            timeout_seconds=float(item.get("timeout_seconds", 30)),
                            output_limit_bytes=int(item.get("output_limit_bytes", 65536)),
                        )
                    )
                chapters.append(
                    Chapter(
                        id=str(chapter_data["id"]),
                        title=str(chapter_data["title"]),
                        experiments=tuple(experiments),
                    )
                )
            parts.append(
                CoursePart(
                    id=str(part_data["id"]),
                    title=str(part_data["title"]),
                    chapters=tuple(chapters),
                )
            )

        expected_count = int(manifest.get("experiment_count", -1))
        actual_count = sum(len(chapter.experiments) for part in parts for chapter in part.chapters)
        if expected_count != actual_count:
            raise CourseValidationError(
                f"实验数量不一致：声明 {expected_count}，实际 {actual_count}"
            )
        return cls(title=str(manifest["title"]), parts=tuple(parts))

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CourseValidationError(f"无法读取课程文件：{path.name}") from error

    @staticmethod
    def _inside(root: Path, relative: str, label: str) -> Path:
        candidate = (root / relative).resolve()
        if not relative or not candidate.is_relative_to(root):
            raise CourseValidationError(f"{label}不允许指向课程包外部：{relative}")
        return candidate


def bundled_course_path() -> Path:
    resource = files("aibox_studio").joinpath("resources", "basic-ai")
    return Path(str(resource))

