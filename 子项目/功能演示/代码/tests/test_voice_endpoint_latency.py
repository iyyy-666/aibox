"""Run the actual recording method on deterministic PCM, without opening a mic."""
import ast
from collections import deque
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
import pytest


def recorder():
    source=Path(__file__).resolve().parents[1]/'voice_engine.py'
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='VoiceEngine')
    method=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='_record_utterance')
    helpers=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in {'clamp_level','trigger_confirmed'}]
    namespace={'np':np,'deque':deque,'time':time,'PRE_ROLL_FRAMES':35,'SAMPLE_RATE':16000,
        'MIN_RECORD_SEC':.46,'MAX_RECORD_SEC':8.,'POST_SILENCE_SEC':.58,
        'FAST_POST_SILENCE_SEC':.38,'SHORT_UTTERANCE_SEC':.92,'GAIN':3.,'TRIGGER_CONFIRM_FRAMES':3}
    exec(compile(ast.Module(body=helpers+[method],type_ignores=[]),str(source),'exec'),namespace)
    return namespace['_record_utterance']


class PCM:
    def __init__(self,segments):
        self.frames=[]
        self.reads=0
        for seconds,speech in segments:
            frame=np.full(160,5000 if speech else 0,np.int16).tobytes()
            self.frames.extend([frame]*int(seconds*100))
    def read(self):
        self.reads+=1
        frame=self.frames[self.reads-1] if self.reads<=len(self.frames) else bytes(320)
        return 160,frame


@pytest.mark.parametrize(('segments','lower','upper'),[
    ([(.2,False),(.8,True),(2,False)],.8,1.6),
    ([(.2,False),(1.5,True),(2,False)],1.5,2.4),
    ([(.2,False),(.7,True),(.2,False),(.7,True),(2,False)],1.6,2.6),
])
def test_recording_ends_after_silence_instead_of_waiting_eight_second_cap(segments,lower,upper):
    pcm=PCM(segments)
    engine=SimpleNamespace(running=True,_dynamic_trigger=.05,_dynamic_silence=.03)
    audio,_=recorder()(engine,pcm)
    duration=len(audio)/32000
    assert lower<duration<=upper
    assert pcm.reads<300


def test_continuous_speech_still_obeys_eight_second_safety_cap():
    pcm=PCM([(10,True)])
    engine=SimpleNamespace(running=True,_dynamic_trigger=.05,_dynamic_silence=.03)
    audio,_=recorder()(engine,pcm)
    assert 7.99<=len(audio)/32000<=8.03
