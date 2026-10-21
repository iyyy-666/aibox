"""Install the reviewed homepage CSS, preserving the previous device file."""
from pathlib import Path
import hashlib, json, shlex, sys, uuid

project = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project / '工具'))
from inspect_board import connect
from deploy_transport import sudo

folder = Path(__file__).resolve().parent
css = project / '代码/feature_demo/web/styles.css'
expected = hashlib.sha256((folder / 'styles.before.css').read_bytes()).hexdigest()
candidate = hashlib.sha256(css.read_bytes()).hexdigest()
stage = '/tmp/aibox-home-' + uuid.uuid4().hex + '.css'
code = r'''
import pathlib,hashlib,shutil,datetime,json,subprocess,os,pwd,time,re,urllib.request
target=pathlib.Path('/root/robot_arm/feature_demo/web/styles.css')
assert hashlib.sha256(target.read_bytes()).hexdigest()==EXPECTED, 'Device CSS changed; stop for review'
backup=pathlib.Path('/root/aibox_backups')/('home-layout-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,exist_ok=False)
shutil.copy2(target,backup/'styles.css')
assert hashlib.sha256(pathlib.Path(STAGE).read_bytes()).hexdigest()==CANDIDATE
shutil.copyfile(STAGE,target)
os.chmod(target,0o644)
assert hashlib.sha256(target.read_bytes()).hexdigest()==CANDIDATE
processes=[]
for proc in pathlib.Path('/proc').iterdir():
 if not proc.name.isdigit():continue
 try:
  args=(proc/'cmdline').read_bytes().split(b'\0')
  if b'feature_demo.launcher' in args:processes.append(int(proc.name))
 except (OSError,PermissionError):pass
launched=False
if not processes:
 account=pwd.getpwnam('ztl');env=os.environ.copy()
 for proc in pathlib.Path('/proc').iterdir():
  try:
   if (proc/'comm').read_text().strip()=='gnome-shell' and proc.stat().st_uid==account.pw_uid:
    env.update(dict(x.split('=',1) for x in (proc/'environ').read_bytes().decode().split('\0') if '=' in x));break
  except (OSError,ValueError):pass
 env.update(DISPLAY=':0',HOME=account.pw_dir,USER='ztl',LOGNAME='ztl',XDG_RUNTIME_DIR='/run/user/%d'%account.pw_uid)
 log=open('/tmp/aibox-home-layout.log','ab')
 p=subprocess.Popen(['/usr/local/bin/feature_demo.sh'],env=env,cwd='/root/robot_arm',stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,user=account.pw_uid,group=account.pw_gid,extra_groups=os.getgrouplist('ztl',account.pw_gid))
 processes=[p.pid];launched=True
port=None
for i in range(50):
 lines=subprocess.check_output(['ss','-ltnp'],text=True)
 for line in lines.splitlines():
  if any(('pid=%d,'%pid) in line for pid in processes):
   match=re.search(r'127\.0\.0\.1:(\d+)',line)
   if match:port=int(match.group(1));break
 if port:break
 time.sleep(.1)
assert port,'Homepage service did not become ready'
base='http://127.0.0.1:%d'%port
state=json.load(urllib.request.urlopen(base+'/api/modules/active'))
assert state['state']=='idle',state
assert hashlib.sha256(urllib.request.urlopen(base+'/styles.css').read()).hexdigest()==CANDIDATE
modules=json.load(urllib.request.urlopen(base+'/api/modules'))['modules']
assert len(modules)==14
pathlib.Path(STAGE).unlink()
print(json.dumps({'backup':str(backup),'sha256':CANDIDATE,'pids':processes,'port':port,'launched':launched,'state':state['state'],'modules':len(modules)},ensure_ascii=False))
'''.replace('EXPECTED',repr(expected)).replace('CANDIDATE',repr(candidate)).replace('STAGE',repr(stage))

with connect() as client:
    with client.open_sftp() as sftp:
        sftp.put(str(css), stage)
    result = sudo(client, 'python3 -c ' + shlex.quote(code), timeout=30)
    (folder / 'deployment.json').write_text(result, encoding='utf-8')
    print(result)
