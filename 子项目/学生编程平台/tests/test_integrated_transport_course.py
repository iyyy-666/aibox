import contextlib
import io
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from aibox_studio.course import CourseCatalog, bundled_course_path
from aibox_studio.policy import CodePolicy


def exercise(text):
    catalog = CourseCatalog.load(bundled_course_path())
    item = catalog.experiment('integrated.voice-transport.01')
    assert CodePolicy(allowed_imports=item.allowed_imports, capabilities=item.capabilities).validate(item.template_code).allowed
    output = io.StringIO()
    with patch.dict(os.environ, {'AIBOX_DEVICE_MODE': 'hardware', 'AIBOX_SIM_VOICE_TEXT': text}), patch('socket.socket', side_effect=AssertionError('must not access hardware')), contextlib.redirect_stdout(output):
        exec(compile(item.template_code, '<student-plan>', 'exec'), {})
    return item, output.getvalue()


@pytest.mark.parametrize('color', ['红色', '绿色', '蓝色', '黄色'])
def test_transport_plan_accepts_four_colors_without_hardware(color):
    item, output = exercise('搬运' + color + '积木到传送带')
    assert item.number == 57
    assert item.capabilities == ('voice.listen',)
    assert color in output
    assert '6.' in output
    assert '模拟' in output
    assert '未验证物理到位' in output


@pytest.mark.parametrize('text', ['张开', '搬运紫色积木到传送带', '不要搬运红色积木到传送带', '搬运红色积木到传送带再搬运蓝色积木到传送带', '', '搬运红色积木'])
def test_transport_plan_rejects_ambiguous_or_incomplete_commands(text):
    _, output = exercise(text)
    assert '口令未匹配' in output
    assert '6.' not in output


def test_sdk_help_explains_actual_device_boundaries():
    from aibox_studio.sdk_help import SDK_HELP
    assert '机械臂' in SDK_HELP and '模拟' in SDK_HELP
    assert 'Voice.listen(timeout=8)' in SDK_HELP
    assert 'arm.pose' in SDK_HELP and 'arm.action' in SDK_HELP
    assert 'SDK 未新增' in SDK_HELP
