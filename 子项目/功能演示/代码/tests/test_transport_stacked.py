from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
from tests.test_transport_vision import adapter

@dataclass
class Detection:
    name: str
    box: tuple
    area: float
    center: tuple
    bgr: tuple = (0, 255, 0)

def detector():
    result = adapter()
    def legacy(image):
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        found = []
        for label, (lo, hi), bgr in result._colors.module.COLOR_RANGES:
            mask = cv2.inRange(hsv, np.array(lo,np.uint8), np.array(hi,np.uint8))
            contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                if cv2.contourArea(contour) > 1800:
                    x,y,w,h = cv2.boundingRect(contour)
                    found.append(Detection(label,(x,y,w,h),cv2.contourArea(contour),(x+w//2,y+h//2),bgr))
        return sorted(found,key=lambda d:d.area,reverse=True)[:4]
    result._colors.module.COLOR_RANGES += [('Red',((170,70,70),(180,255,255)),(0,0,255)),('Cyan',((86,45,60),(99,255,255)),(255,255,0))]
    result._colors.instance = SimpleNamespace(_detect_colors=legacy,_annotate=lambda frame,dets:frame)
    return result

def test_real_stacked_scene_detects_four_faces_without_reflections():
    path=Path(__file__).parent/'fixtures/transport-stacked.png'
    frame=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    _,event=detector().process(frame)
    blocks=event['result']
    assert sorted(b['color'] for b in blocks)==['blue','green','red','yellow']
    for b in blocks:
        x,y,w,h=b['box']
        assert 195 < x < 320 and 95 < y < 225 and y+h < 310
        assert 65 < w < 120 and 65 < h < 125

def test_washed_red_and_warm_yellow_are_found_without_legacy_candidates():
    frame=np.full((480,640,3),30,np.uint8)
    hsv=np.uint8([[[2,60,255],[17,130,195]]])
    bgr=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)[0]
    cv2.rectangle(frame,(220,170),(300,250),tuple(map(int,bgr[0])),-1)
    cv2.rectangle(frame,(310,170),(390,250),tuple(map(int,bgr[1])),-1)
    d=detector();d._colors.instance._detect_colors=lambda _:[]
    assert sorted(b['color'] for b in d.process(frame)[1]['result'])==['red','yellow']

def test_touching_red_faces_are_not_merged_across_separate_objects():
    frame=np.full((480,640,3),30,np.uint8)
    cv2.rectangle(frame,(150,170),(220,240),(0,0,240),-1)
    cv2.rectangle(frame,(360,170),(430,240),(0,0,240),-1)
    blocks=detector().process(frame)[1]['result']
    assert len([b for b in blocks if b['color']=='red'])==2

def test_white_faces_are_never_inferred_as_yellow_from_position():
    frame=np.full((480,640,3),30,np.uint8)
    cv2.rectangle(frame,(310,210),(390,290),(252,252,252),-1)
    assert detector().process(frame)[1]['result']==[]

