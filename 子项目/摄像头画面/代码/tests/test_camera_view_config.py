import ast
from pathlib import Path


def test_camera_preview_default_refreshes_at_30_fps() -> None:
    source = Path(__file__).resolve().parents[1] / "camera_view_app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    values = {
        node.targets[0].id: int(node.value.args[0].args[1].value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and node.targets[0].id == "DISPLAY_INTERVAL_MS"
    }
    assert values["DISPLAY_INTERVAL_MS"] <= 34
