from types import SimpleNamespace
import pytest
from tests.test_worker_entry import FakeCv2, FakeAdapter, ReadyGimbal
from feature_demo.workers.runtime import _configured_camera, create_vision_worker
from feature_demo.adapters.vision import LEGACY_VISION_SPECS

@pytest.mark.parametrize('module',list(LEGACY_VISION_SPECS))
def test_every_visual_module_applies_manual_exposure_on_each_camera_open(module):
    cv=FakeCv2()
    worker=create_vision_worker(module,cv2_module=cv,adapter_builder=lambda _:FakeAdapter(),event_sink=lambda _:None,gimbal=ReadyGimbal())
    assert cv.created==[]
    first=worker._camera_factory();second=worker._camera_factory()
    for capture in [first,second]:
        assert (21,1) in capture.settings
        assert (15,180) in capture.settings
    assert first is not second

@pytest.mark.parametrize('failure',['write','readback'])
def test_fixed_exposure_failure_releases_camera_instead_of_running_with_wrong_value(failure):
    class Capture:
        released=False
        def set(self,key,value):return not (failure=='write' and key==15)
        def get(self,key):return 156 if key==15 else 1
        def release(self):self.released=True
    capture=Capture();cv=FakeCv2();cv.VideoCapture=lambda *args:capture
    with pytest.raises(RuntimeError):_configured_camera(cv,'/dev/fake')
    assert capture.released

def test_transport_no_longer_accepts_an_exposure_adjustment_command(rig):
    worker,*_=rig
    with pytest.raises(ValueError):worker.command('set_exposure',{'value':156})
from tests.test_transport import rig
