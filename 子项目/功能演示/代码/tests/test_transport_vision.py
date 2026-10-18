"""Real contour checks must exclude backgrounds, marks and unstable geometry."""
from types import SimpleNamespace
import cv2
import numpy as np
import pytest

from feature_demo.adapters.transport_vision import TransportVisionAdapter


def adapter():
    # Only the color detector is replaced; contour confirmation runs on real pixels.
    class Colors:
        module = SimpleNamespace(cv2=cv2, np=np, COLOR_RANGES=[
            ('Blue', ((100, 55, 45), (130, 255, 255)), (255, 0, 0)),
            ('Red', ((0, 70, 70), (10, 255, 255)), (0, 0, 255)),
            ('Green', ((37, 45, 45), (85, 255, 255)), (0, 255, 0)),
            ('Yellow', ((25, 70, 80), (36, 255, 255)), (0, 255, 255)),
        ])
        instance = None
        def close(self):
            pass
    return TransportVisionAdapter(Colors(), split_stereo=lambda f: (f, f),
        box_is_target=lambda image, box, **kwargs: True)


@pytest.mark.parametrize(('color', 'bgr'), [('blue', (255, 0, 0)),
    ('red', (0, 0, 255)), ('green', (0, 255, 0)), ('yellow', (0, 255, 255))])
def test_solid_block_footprint_in_fixed_roi_is_confirmed(color, bgr):
    frame = np.full((480, 640, 3), 220, np.uint8)
    cv2.rectangle(frame, (280, 200), (350, 270), bgr, -1)
    candidate = {'name': color.title(), 'box': (280, 200, 71, 71)}
    assert adapter().confirm_block(frame, candidate) is True


@pytest.mark.parametrize('kind', ['background', 'thin_mark', 'circle', 'hollow', 'edge', 'concave'])
def test_colored_regions_are_not_enough_to_confirm_block(kind):
    frame = np.full((480, 640, 3), 220, np.uint8)
    box = (280, 200, 71, 71)
    if kind == 'background':
        frame[:] = (255, 0, 0)
        box = (0, 0, 640, 480)
    elif kind == 'thin_mark':
        cv2.rectangle(frame, (280, 200), (350, 212), (255, 0, 0), -1)
        box = (280, 200, 71, 13)
    elif kind == 'circle':
        cv2.circle(frame, (315, 235), 35, (255, 0, 0), -1)
    elif kind == 'hollow':
        cv2.rectangle(frame, (280, 200), (350, 270), (255, 0, 0), 3)
    elif kind == 'edge':
        cv2.rectangle(frame, (0, 200), (70, 270), (255, 0, 0), -1)
        box = (0, 200, 71, 71)
    else:
        cv2.rectangle(frame, (280, 200), (350, 270), (255, 0, 0), -1)
        cv2.rectangle(frame, (310, 200), (350, 240), (220, 220, 220), -1)
    assert adapter().confirm_block(frame, {'name': 'Blue', 'box': box}) is False


def test_cube_three_faces_and_dark_reflection_are_separated():
    from dataclasses import dataclass
    @dataclass
    class Detection:
        name: str
        box: tuple
        area: float
        center: tuple
    frame = np.full((480,640,3), 35, np.uint8)
    cube = np.array([[280,180],[320,165],[355,180],[355,245],[320,263],[280,245]],np.int32)
    cv2.fillConvexPoly(frame, cube, (255,255,0))
    cv2.rectangle(frame,(285,250),(350,330),(70,70,0),-1)
    detector = adapter()
    detector._colors.module.COLOR_RANGES.append(('Cyan',((86,45,60),(99,255,255)),(255,255,0)))
    refined = detector.refine_detection(frame, Detection('Cyan',(280,165,76,166),9000,(318,248)))
    assert refined is not None
    assert refined.box[3] < 110
    assert detector.confirm_block(frame, {'name':refined.name,'box':refined.box})
