from pathlib import Path

import pytest

from aibox_studio.course import CourseCatalog, bundled_course_path
from aibox_studio.runner import RunRequest, Runner


COURSE_ROOT = bundled_course_path()
CATALOG = CourseCatalog.load(COURSE_ROOT)


@pytest.mark.parametrize(
    "experiment",
    CATALOG.experiments,
    ids=lambda item: f"{item.number:02d}-{item.id}",
)
def test_every_bundled_template_passes_policy_and_simulated_execution(experiment):
    result = Runner().run(
        RunRequest(
            code=experiment.template_code,
            allowed_imports=experiment.allowed_imports,
            capabilities=experiment.capabilities,
            timeout_seconds=5,
            output_limit_bytes=experiment.output_limit_bytes,
        )
    )

    assert result.status == "completed", result.diagnostics or result.stderr
