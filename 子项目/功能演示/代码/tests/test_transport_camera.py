import pytest
from tests.test_transport import rig

def test_camera_close_failure_still_releases_gimbal():
    from feature_demo.workers.vision import VisionWorker
    from types import SimpleNamespace
    calls=[]
    def broken():raise RuntimeError('exposure restore failed')
    vision=VisionWorker(adapter=SimpleNamespace(close=broken),camera_factory=lambda:None,
        encode_frame=lambda _:b'',event_sink=lambda _:None,
        gimbal=SimpleNamespace(close=lambda:calls.append('gimbal')))
    with pytest.raises(RuntimeError):vision.stop()
    assert calls==['gimbal']

def test_transport_camera_close_failure_still_disconnects_robot(rig):
    worker,motion,*_=rig
    old=worker._vision.stop
    def broken():raise RuntimeError('exposure restore failed')
    worker._vision.stop=broken
    try:
        with pytest.raises(RuntimeError):worker.stop()
        assert motion.closed
    finally:worker._vision.stop=old

