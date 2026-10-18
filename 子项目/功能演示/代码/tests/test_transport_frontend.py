import json
from pathlib import Path
import subprocess


def test_transport_controls_render_and_follow_real_worker_state():
    app = Path(__file__).resolve().parents[1] / 'feature_demo/web/app.js'
    script = r'''
const assert = require('node:assert/strict');
const nodes = new Map();
const controls = [{dataset:{command:'start_listening'}}, {dataset:{command:'stop_listening'}}];
function node(selector) {
  if (!nodes.has(selector)) nodes.set(selector, {textContent:'',innerHTML:'',hidden:false,
    style:{},classList:{add(){},remove(){},toggle(){}},replaceChildren(){}});
  return nodes.get(selector);
}
globalThis.__FEATURE_DEMO_TEST__ = true;
globalThis.document = {querySelector:node,querySelectorAll(s){return s === '[data-command]' ? controls : [];}};
globalThis.window = {};
require(APP_PATH);
const hooks = globalThis.__featureDemoTestHooks;
hooks.appState.active = {module_id:'voice_transport',visual:true};
hooks.renderVisualActions(hooks.appState.active);
assert.match(node('[data-visual-actions]').innerHTML, /开启监听/);
assert.match(node('[data-visual-actions]').innerHTML, /停止监听/);
assert.match(node('[data-visual-actions]').innerHTML, /未监听/);
hooks.renderWorkerDetails({transport:true, listening_status:'正在监听', phase:'waiting', raw:'搬运蓝色物块到传送带上', target_label:'蓝色', block_confirmed:false,busy:false,locked:false});
assert.equal(node('[data-transport-listening]').textContent, '正在监听');
assert.equal(controls[0].disabled, true);
assert.equal(controls[1].disabled, false);
hooks.renderWorkerDetails({transport:true, listening_status:'已停止',phase:'moving',target_label:'蓝色',block_confirmed:true,busy:true,locked:false,message:'正在执行搬运。'});
assert.equal(node('[data-transport-listening]').textContent, '已停止');
assert.equal(node('[data-transport-block]').textContent, '已确认对应物块');
assert.equal(controls[0].disabled, true);
assert.equal(controls[1].disabled, false);
hooks.renderWorkerDetails({transport:true,listening_status:'已停止',phase:'completed',busy:false,locked:false});
assert.equal(controls[0].disabled, false);
hooks.renderWorkerDetails({transport:true,listening_status:'监听错误',phase:'fault',busy:true,locked:true, raw:'<img src=x onerror=alert(1)>'});
assert.equal(node('[data-transport-raw]').textContent, '<img src=x onerror=alert(1)>');
assert.equal(controls[0].disabled, true);
'''.replace('APP_PATH', json.dumps(str(app)))
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
