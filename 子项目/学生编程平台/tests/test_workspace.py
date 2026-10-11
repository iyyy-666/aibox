from aibox_studio.course import Experiment
from aibox_studio.workspace import WorkspaceStore


def make_experiment():
    return Experiment(
        id="intro.01",
        number=1,
        title="第一个实验",
        description="",
        template_code="print('模板')\n",
        allowed_imports=(),
        capabilities=(),
        resources=(),
        panel="text",
        run_mode="oneshot",
        timeout_seconds=10,
        output_limit_bytes=4096,
    )


def test_workspace_returns_template_until_student_saves(tmp_path):
    store = WorkspaceStore(tmp_path)

    assert store.load(make_experiment()) == "print('模板')\n"


def test_workspace_saves_code_by_stable_experiment_id(tmp_path):
    store = WorkspaceStore(tmp_path)
    experiment = make_experiment()

    store.save(experiment, "print('学生代码')\n")

    assert store.load(experiment) == "print('学生代码')\n"
    assert (tmp_path / "experiments" / "intro.01.py").exists()


def test_workspace_reset_restores_template_and_keeps_backup(tmp_path):
    store = WorkspaceStore(tmp_path)
    experiment = make_experiment()
    store.save(experiment, "print('学生代码')\n")

    restored = store.reset(experiment)

    assert restored == "print('模板')\n"
    assert store.load(experiment) == "print('模板')\n"
    assert list((tmp_path / "backups").glob("intro.01-*.py"))
