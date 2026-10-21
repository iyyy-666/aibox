from pathlib import Path
import shlex, sys
folder=Path(__file__).resolve().parent
sys.path.insert(0,str(folder.parents[1]/'工具'))
from inspect_board import connect
from deploy_transport import sudo

code="""
import os
os.environ['DISPLAY']=':0'
import gi
gi.require_version('Gdk','3.0')
from gi.repository import Gdk
window=Gdk.get_default_root_window()
image=Gdk.pixbuf_get_from_window(window,0,0,window.get_width(),window.get_height())
assert image.savev('/tmp/aibox-home-layout.png','png',[],[])
"""
with connect() as client:
    print(sudo(client,'python3 -c '+shlex.quote(code)))
    image=sudo(client,'cat /tmp/aibox-home-layout.png',binary=True)
    (folder/'device.png').write_bytes(image)
print(folder/'device.png')
