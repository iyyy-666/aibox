import json,subprocess
from pathlib import Path

def test_camera_refresh_paces_the_whole_request_and_drops_late_module_frames():
    app=Path(__file__).resolve().parents[1]/'feature_demo/web/app.js'
    code=r'''
const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
const image={dataset:{},hidden:false,src:'old'};
const empty={hidden:false,querySelector(){return {textContent:''}}};
const nodes=new Map();
globalThis.__FEATURE_DEMO_TEST__=true;
globalThis.document={hidden:false,querySelector(s){if(s==='[data-camera-frame]')return image;if(s==='[data-frame-empty]')return empty;if(!nodes.has(s))nodes.set(s,{textContent:''});return nodes.get(s)},querySelectorAll(){return []}};
globalThis.window={setTimeout(){throw Error('stale module should not schedule another frame')}};
vm.runInThisContext(fs.readFileSync(APP,'utf8')+';globalThis.cameraHooks={appState,refreshFrame,frameRefreshDelay,updateFramePerformance};');
const h=globalThis.cameraHooks;
assert.ok(h.frameRefreshDelay('color_recognition',25)<=9);
assert.ok(h.frameRefreshDelay('color_recognition',25)>=7);
document.hidden=true;assert.equal(h.frameRefreshDelay('color_recognition',25),500);document.hidden=false;
h.appState.frameDisplayTimes=[performance.now()-3000,performance.now()-2900];
h.updateFramePerformance({capture_fps:14,processing_fps:14});
assert.match(nodes.get('[data-camera-performance]').textContent,/图像加载 0.0/);
let resolveFetch;globalThis.fetch=()=>new Promise(resolve=>{resolveFetch=resolve});
let created=0;globalThis.URL={createObjectURL(){created++;return 'new'},revokeObjectURL(){}};
h.appState.active={module_id:'color_recognition'};h.appState.frameGeneration=4;
const pending=h.refreshFrame('color_recognition',4);
h.appState.frameGeneration=5;h.appState.active={module_id:'shape_recognition'};
resolveFetch({status:200,headers:{get(){return '8'}},blob:async()=>({})});
pending.then(()=>{assert.equal(created,0);assert.equal(image.src,'old');}).catch(e=>{console.error(e);process.exitCode=1});
'''.replace('APP',json.dumps(str(app)))
    r=subprocess.run(['node','-e',code],capture_output=True,text=True,encoding='utf-8')
    assert r.returncode==0,r.stderr
