import base64,time,threading
import pytest
from tests.test_api import client,manager
from tests.test_vision_workers import FakeCamera,FakeVisionAdapter
from feature_demo.workers.vision import VisionWorker

def test_duplicate_frame_is_not_transmitted_and_sequence_reset_still_works(client,manager):
    client.post('/api/modules/color_recognition/start')
    manager._worker.snapshot=lambda:{'frame_jpeg_base64':base64.b64encode(b'jpeg').decode(),'frame_sequence':7}
    response=client.get('/api/modules/color_recognition/frame?after_sequence=7')
    assert response.status_code==204 and response.content==b''
    assert client.get('/api/modules/color_recognition/frame?after_sequence=100').content==b'jpeg'

def test_status_websocket_does_not_retransmit_jpeg_bytes(client,manager):
    client.post('/api/modules/color_recognition/start')
    manager._worker.snapshot=lambda:{'frame_jpeg_base64':base64.b64encode(b'jpeg').decode(),'frame_sequence':7,'result':['blue']}
    with client.websocket_connect('/ws/modules/color_recognition') as socket:
        data=socket.receive_json()
    assert 'frame_jpeg_base64' not in data['details']
    assert data['details']['result']==['blue']
    assert client.get('/api/modules/color_recognition/frame').content==b'jpeg'

def test_worker_reports_measured_capture_processing_and_age_without_frame_backlog():
    frames=[];ready=threading.Event()
    class Slow(FakeVisionAdapter):
        def process(self,frame):time.sleep(.02);return super().process(frame)
    def sink(event):
        if event.get('type')=='frame':
            frames.append(event)
            if len(frames)>=5:ready.set()
    worker=VisionWorker(adapter=Slow([]),camera_factory=lambda:FakeCamera([]),encode_frame=lambda _:b'jpeg',event_sink=sink)
    worker.start()
    try:assert ready.wait(2)
    finally:worker.stop()
    metrics=frames[-1]['performance']
    assert metrics['capture_fps']>metrics['processing_fps']>0
    assert metrics['capture_frames']>=metrics['processed_frames']
    assert 0<=metrics['frame_age_ms']<200
    assert metrics['algorithm_ms']>=15

def test_transport_color_conversion_is_shared_for_the_same_real_frame(monkeypatch):
    from pathlib import Path
    import cv2,numpy as np
    from tests.test_transport_stacked import detector
    frame=cv2.imdecode(np.frombuffer((Path(__file__).parent/'fixtures/transport-stacked.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    calls=[];original=cv2.cvtColor
    def measured(*args,**kwargs):
        if args[1]==cv2.COLOR_BGR2HSV:calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(cv2,'cvtColor',measured)
    _,event=detector().process(frame)
    assert sorted(b['color'] for b in event['result'])==['blue','green','red','yellow']
    assert len(calls)==1
