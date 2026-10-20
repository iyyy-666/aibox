"""Reuse legacy color segmentation and the sorting camera view/ROI.

The extra contour gate confirms a compact block footprint, not just color pixels.
A printed square identical to a block face cannot be distinguished by this 2D
gate; the physical pickup ROI must be calibrated and cleared before hardware use.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace

import numpy as np


@dataclass(frozen=True)
class BlockDetection:
    name: str
    box: tuple
    area: float
    center: tuple
    bgr: tuple


# Four supported physical block colors. The board camera renders the yellow
# face at H=15..18 under warm light. Keep a saturation floor: white is unknown.
BLOCK_COLORS = {
    'Red': (((0, 45, 45), (10, 255, 255)), ((170, 45, 45), (179, 255, 255))),
    'Yellow': (((14, 65, 65), (36, 255, 255)),),
    'Green': (((37, 45, 35), (84, 255, 255)),),
    'Blue': (((85, 35, 35), (142, 255, 255)),),
}
BLOCK_BGR = {'Red': (45, 45, 235), 'Yellow': (0, 225, 255),
             'Green': (80, 210, 80), 'Blue': (235, 120, 45)}


class TransportVisionAdapter:
    def __init__(self, colors, *, split_stereo, box_is_target, observer=None, roi=None):
        self._colors = colors
        self._split_stereo = split_stereo
        self._box_is_target = box_is_target
        self._observer = observer
        self._roi = tuple(roi) if roi is not None else None
        if self._roi is not None:
            if len(self._roi) != 4 or not (0 <= self._roi[0] < self._roi[2] <= 1
                                          and 0 <= self._roi[1] < self._roi[3] <= 1):
                raise ValueError('物块检测区域须为归一化的 [x1,y1,x2,y2]。')

    def set_observer(self, observer):
        self._observer = observer

    def _mask(self, patch, name, hsv=None):
        cv2 = self._colors.module.cv2
        if hsv is None:
            hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        mask = np.zeros(patch.shape[:2], np.uint8)
        label = 'Blue' if name.lower() == 'cyan' else name.title()
        for lower, upper in BLOCK_COLORS.get(label, ()):
            mask |= cv2.inRange(hsv, np.array(lower,np.uint8),np.array(upper,np.uint8))
        return mask, hsv

    def _detect_blocks(self, frame, hsv=None):
        cv2 = self._colors.module.cv2
        candidates = []
        kernel = np.ones((3, 3), np.uint8)
        for name in BLOCK_COLORS:
            mask, _ = self._mask(frame, name, hsv)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            # No global top-four cutoff and no union of separate red objects.
            for contour in contours:
                area = float(cv2.contourArea(contour))
                if area < frame.shape[0] * frame.shape[1] * .004:
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                candidates.append(BlockDetection(name, (x,y,w,h), area,
                                  (x+w//2,y+h//2), BLOCK_BGR[name]))
        return candidates

    def refine_detection(self, frame, detection, hsv=None):
        cv2 = self._colors.module.cv2
        x,y,w,h = map(int,detection.box)
        mask,hsv = self._mask(frame[y:y+h,x:x+w], detection.name,
                              None if hsv is None else hsv[y:y+h,x:x+w])
        values = hsv[:,:,2][mask > 0]
        if values.size == 0:
            return None
        # The shiny black worktop joins the real cube to its darker reflection.
        # Split on brightness within the existing color candidate, not new colors.
        mask[hsv[:,:,2] < max(45, float(np.percentile(values,90)) * .68)] = 0
        contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        contour = max(contours,key=cv2.contourArea)
        bx,by,bw,bh = cv2.boundingRect(contour)
        return replace(detection, box=(x+bx,y+by,bw,bh), area=float(cv2.contourArea(contour)),
                       center=(x+bx+bw//2,y+by+bh//2))

    def confirm_block(self, frame, candidate, hsv=None):
        cv2 = self._colors.module.cv2
        x, y, w, h = map(int, candidate['box'])
        height, width = frame.shape[:2]
        # Default ROI uses the SAME margins as sorting's box_is_target().
        rx1, ry1, rx2, ry2 = self._roi or (.13, .10, .87, .90)
        if not (width * rx1 < x and height * ry1 < y
                and x + w < width * rx2 and y + h < height * ry2):
            return False
        if not (min(w, h) >= 24 and .55 <= w / max(1, h) <= 1.8
                and .004 <= w * h / (width * height) <= .12):
            return False
        if not self._box_is_target(frame, (x, y, x + w, y + h),
                                   min_area=width * height * .004,
                                   max_area_ratio=.12, min_side=24):
            return False
        patch = frame[y:y + h, x:x + w]
        mask, hsv = self._mask(patch, candidate['name'],
                                None if hsv is None else hsv[y:y+h,x:x+w])
        # Extent rejects outlines, scattered pixels and gaps; hull solidity rejects
        # irregular objects. Four corners reject circles and colored blobs.
        if cv2.countNonZero(mask) < w * h * .80:
            return False
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return False
        contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(contour)
        hull_area = cv2.contourArea(cv2.convexHull(contour))
        if hull_area <= 0 or area / hull_area < .92:
            return False
        polygon = cv2.approxPolyDP(contour, .035 * cv2.arcLength(contour, True), True)
        return 4 <= len(polygon) <= 6 and cv2.isContourConvex(polygon)

    def process(self, frame):
        normal, _ = self._split_stereo(frame)
        hsv = self._colors.module.cv2.cvtColor(normal, self._colors.module.cv2.COLOR_BGR2HSV)
        colors = self._detect_blocks(normal, hsv)
        blocks, confirmed = [], []
        for detection in colors:
            color = str(detection.name).lower()
            if color == 'cyan':
                color = 'blue'
            if color not in {'red', 'green', 'yellow', 'blue'}:
                continue
            detection = self.refine_detection(normal, detection, hsv)
            if detection is None:
                continue
            if self.confirm_block(normal, {'name': detection.name, 'box': detection.box}, hsv):
                if any(abs(item['box'][0]-detection.box[0]) < 12 and abs(item['box'][1]-detection.box[1]) < 12 for item in blocks):
                    continue
                blocks.append({'color': color, 'box': list(detection.box), 'is_block': True})
                confirmed.append(detection)
        if self._observer is not None:
            self._observer(blocks)
        annotated = self._colors.instance._annotate(normal, confirmed)
        if self._roi is not None:
            cv2 = self._colors.module.cv2
            height, width = normal.shape[:2]
            x1, y1, x2, y2 = self._roi
            cv2.rectangle(annotated, (int(x1 * width), int(y1 * height)),
                          (int(x2 * width), int(y2 * height)), (0, 220, 220), 2)
        return annotated, {'result': blocks}

    def close(self):
        self._colors.close()


def build_transport_vision(builder):
    colors = builder('color_recognition')
    sorting = builder('object_sorting')
    roi_setting = os.getenv('AIBOX_TRANSPORT_PICK_ROI', '')
    return TransportVisionAdapter(colors, split_stereo=sorting.module.split_stereo,
        box_is_target=sorting.module.box_is_target,
        roi=json.loads(roi_setting) if roi_setting else None)
