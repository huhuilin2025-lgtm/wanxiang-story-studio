"""Nadou operations exclusively through installed official CLI, no credential access."""
import base64,hashlib,json,os,re,shutil,subprocess,threading,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent;RUNTIME=ROOT/'.runtime';PROJECT=ROOT.parent
CLI=Path(os.environ.get('NADOU_CLI') or shutil.which('nadou') or str(ROOT/'.missing-nadou'))
MUTEX=threading.RLock();LOGIN=None
def run(args,payload=None,timeout=90):
 proc=subprocess.run([str(CLI),*args,'--no-interactive','--json'],input=json.dumps(payload,ensure_ascii=False) if payload is not None else None,text=True,capture_output=True,timeout=timeout)
 try:r=json.loads(proc.stdout)
 except ValueError:raise ValueError('纳逗CLI未返回有效结果，请检查本地安装或登录状态')
 if proc.returncode or r.get('ok') is False or r.get('success') is False or r.get('error'):
  e=r.get('error') or {};raise ValueError('纳逗：'+str(e.get('code','') if isinstance(e,dict) else e)+' '+str(e.get('message','操作未完成') if isinstance(e,dict) else ''))
 return r
def status():
 if not CLI.exists():return {'connected':False,'message':'未安装纳逗CLI'}
 version=run(['version']);mode=version.get('meta',{}).get('auth_mode');result={'version':version.get('data',{}),'auth_mode':mode}
 try:
  if mode and 'oauth' in str(mode).lower():run(['auth','status'])
  models=run(['model','list','--scenario','multi_reference']);result.update(connected=True,message='CLI模型目录可访问',models=models.get('data'))
 except Exception as e:result.update(connected=False,message=str(e))
 return result
def data(r):return r.get('data',{})
def persist(record):
 path=RUNTIME/('nadou-'+record['id']+'.json');tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(record,ensure_ascii=False,indent=2));os.replace(tmp,path)
def retrieve(ident):
 if not re.fullmatch(r'[a-f0-9-]{36}',ident):raise ValueError('计划ID无效')
 return json.loads((RUNTIME/('nadou-'+ident+'.json')).read_text())
def local_media(value,ident):
 if value.startswith('assets/'):
  p=(ROOT/'dist'/value).resolve();base=(ROOT/'dist/assets').resolve()
 elif value.startswith('/media/'):
  p=(RUNTIME/value.lstrip('/')).resolve();base=(RUNTIME/'media').resolve()
 elif value.startswith('data:'):
  header,encoded=value.split(',',1)
  if not re.match(r'data:(image/(png|jpeg|webp)|audio/[\w.+-]+);base64$',header):raise ValueError('不支持此素材格式')
  p=RUNTIME/(ident+('.png' if header.startswith('data:image/png') else '.jpg' if header.startswith('data:image/jpeg') else '.webp' if header.startswith('data:image/webp') else '.mp3' if 'audio/mpeg' in header or 'audio/mp3' in header else '.m4a' if 'audio/mp4' in header else '.ogg' if 'audio/ogg' in header else '.webm' if 'audio/webm' in header else '.wav'));p.write_bytes(base64.b64decode(encoded));return p
 else:raise ValueError('请先把素材导入本地工作台')
 if not p.is_relative_to(base) or not p.is_file():raise ValueError('素材文件不可用')
 return p

def collect_nodes(obj):
 if isinstance(obj,dict):
  if isinstance(obj.get('nodes'),list):return obj['nodes']
  for v in obj.values():
   found=collect_nodes(v)
   if found:return found
 return []
def new_id():return data(run(['canvas','node','new-id']))['node_id']
def snapshot(canvas):return run(['canvas','get','--canvas-id',canvas,'--raw'])
def graph_hash(graph):
 d=data(graph);stable={k:d[k] for k in ('nodes','edges') if k in d}
 return hashlib.sha256(json.dumps(stable or d,sort_keys=True).encode()).hexdigest()
def sync_worker(rec):
 try:
  rec['status']='running';persist(rec);snapshot(rec['canvas_id']);operations=[];video_ids=[]
  for i,s in enumerate(rec['shots']):
   source_ids=[]
   for kind,value in [('image',s.get('image')), *([('audio',s['audio'])] if s.get('audio') else [('audio',c['url']) for c in s.get('audioClips',[]) if c.get('url')])]:
    if not value:continue
    mutation=str(uuid.uuid4());stage={'shot_id':s['id'],'kind':kind,'mutation_id':mutation,'status':'submitting'};rec['stages'].append(stage);persist(rec)
    file=local_media(value,mutation)
    response=run(['canvas','node','upload-media','--canvas-id',rec['canvas_id'],'--file',str(file),'--media-type',kind,'--label',f'S{i+1:02} {s["title"]} {kind}','--idempotency-key',mutation,'--return-snapshot'],timeout=180)
    stage.update(status='succeeded',response=response);persist(rec)
    d=data(response);ident=d.get('node_id') or (d.get('created_node_ids') or [None])[0]
    if not ident:raise ValueError('素材已上传，但未识别节点ID。请核对保存的回执，不要重新同步。')
    source_ids.append(ident)
   for label,text in [('镜头提示词',s.get('prompt') or s.get('description','')),('配音台词',s.get('dialogue') or '无对白')]:
    ident=new_id();operations.append({'type':'CREATE_NODE','node':{'id':ident,'type':'text','data':{'label':f'S{i+1:02} {label}','text':text,'prompt':''}}});source_ids.append(ident)
   vid=new_id();video_ids.append(vid)
   operations.append({'type':'CREATE_NODE','node':{'id':vid,'type':'video','data':{'label':f'S{i+1:02} {s["title"]} 视频','prompt':f'参考相连关键帧与镜头描述生成视频。{s.get("prompt") or s.get("description","")}\n对白参考：{s.get("dialogue","")}。角色声音以后期确认音轨为准。','modelName':rec['model'],'modelType':'VIDEO','taskType':'MULTI_REF_IMG2VIDEO','modelParams':rec.get('shot_params',{}).get(s['id'],rec['params'])}}})
   operations.extend({'type':'CREATE_EDGE','edge':{'source':source,'target':vid}} for source in source_ids)
  mutation=str(uuid.uuid4());rec.update(graph_mutation_id=mutation,video_nodes=video_ids,graph_request={'operations':operations});persist(rec)
  rec['graph_response']=run(['canvas','graph','mutate','--canvas-id',rec['canvas_id'],'--stdin','--auto-layout-only','--idempotency-key',mutation,'--return-snapshot','--verify-text'],rec['graph_request'],180);persist(rec)
  rec['snapshot']=snapshot(rec['canvas_id']);found={x['id']:x for x in collect_nodes(data(rec['snapshot']))}
  required=[o['node']['id'] for o in operations if o['type']=='CREATE_NODE']
  if not all(x in found for x in required):raise ValueError('写后回读未核实全部节点，请查看原画布，禁止重复同步')
  rec.update(status='succeeded',message='关键帧、文本及视频节点已同步；尚未扣费生成')
 except Exception as e:rec.update(status='unknown' if rec['stages'] or rec.get('graph_mutation_id') else 'failed',error=str(e))
 persist(rec)
def dispatch(action,d):
 global LOGIN
 if action=='login':
  if LOGIN and LOGIN.poll() is None:return {'message':'登录窗口已打开，请完成授权后检查连接'}
  state=status()
  if state.get('connected'):return {'message':'已经连接，无需再次登录'}
  if not any(code in state.get('message','') for code in ('CREDENTIAL_NOT_FOUND','AUTH_REQUIRED','TOKEN_EXPIRED','UNAUTHENTICATED')):raise ValueError('当前错误不是明确的缺失登录凭证，请先检查CLI状态')
  if not d.get('confirmed'):raise ValueError('请确认打开官方登录页面')
  LOGIN=subprocess.Popen([str(CLI),'auth','login','--timeout','10m','--json'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  return {'message':'已启动官方登录流程，请在浏览器完成授权，然后检查连接'}
 if action=='discover':return {'canvases':data(run(['canvas','list','--scope','owner','--size','100'])),'models':data(run(['model','list','--scenario','multi_reference']))}
 if action=='schema':return data(run(['model','schema',d['model'],'--scenario','multi_reference']))
 if action=='plan':
  canvas=str(d.get('canvas_id','')).strip();model=str(d.get('model','')).strip()
  if not canvas or not model:raise ValueError('请选择实际目标画布和模型')
  shots=d.get('shots',[])
  if not shots or not all(s.get('image') for s in shots):raise ValueError('同步镜头需要真实关键帧')
  graph=snapshot(canvas);schema=data(run(['model','schema',model,'--scenario','multi_reference']))
  defaults=schema.get('schema',{}).get('defaults',schema.get('defaults',{}));params={**defaults,**d.get('params',{}),'model':model,'ratio':d.get('ratio','16:9')}
  shot_params={};limits=schema.get('schema',{}).get('limits',{});duration_limit=limits.get('duration',{})
  for shot in shots:
   dur=float(d.get('params',{}).get('duration',shot.get('duration',params.get('duration',5))))
   if isinstance(duration_limit,dict):dur=max(float(duration_limit.get('min',dur)),min(float(duration_limit.get('max',dur)),dur))
   audio_count=1 if shot.get('audio') else len(shot.get('audioClips',[]))
   if audio_count>limits.get('max_audios',999):raise ValueError('镜头配音片段超出该模型参考音频数量上限，请先合并音轨')
   shot_params[shot['id']]={**params,'duration':str(int(dur) if dur.is_integer() else dur)}
  rec={'id':str(uuid.uuid4()),'status':'planned','canvas_id':canvas,'model':model,'params':params,'shots':shots,'shot_params':shot_params,'stages':[],'schema':schema,'created_at':time.time()};persist(rec)
  return {'id':rec['id'],'canvas_id':canvas,'model':model,'params':params,'durations':[{'title':s.get('title',s['id']),'duration':shot_params[s['id']]['duration']} for s in shots],'shots':len(shots),'uploads':sum(1+(1 if s.get('audio') else len(s.get('audioClips',[]))) for s in shots),'message':'将素材登记并创建画布节点、文本和依赖连线；本步不提交视频生成。'}
 if action=='sync':
  with MUTEX:
   rec=retrieve(d['plan_id'])
   if rec['status']!='planned':return {k:v for k,v in rec.items() if k not in ('shots','schema','snapshot','graph_request')}
   if not d.get('confirmed'):raise ValueError('请先确认同步素材与目标画布')
   rec['status']='queued';persist(rec);threading.Thread(target=sync_worker,args=(rec,),daemon=True).start()
  return {'id':rec['id'],'status':'queued'}
 if action=='result':return {k:v for k,v in retrieve(d['plan_id']).items() if k not in ('shots','schema','snapshot','graph_request')}
 if action=='estimate':
  canvas=d['canvas_id'];node=d['node_id'];graph=snapshot(canvas);estimate=run(['canvas','node','estimate','--canvas-id',canvas,'--node-id',node,'--audio-intent','auto'])
  rec={'id':str(uuid.uuid4()),'status':'estimated','canvas_id':canvas,'node_id':node,'estimate':estimate,'graph_hash':graph_hash(graph)};persist(rec);return rec
 if action=='generate':
  with MUTEX:
   rec=retrieve(d['estimate_id'])
   if rec['status']!='estimated':return rec
   if not d.get('confirmed'):raise ValueError('请确认预计积分与生成范围')
   graph=snapshot(rec['canvas_id'])
   if graph_hash(graph)!=rec['graph_hash']:raise ValueError('画布已变化，请重新估价')
   rec['status']='submitting';persist(rec)
   try:rec['submission']=run(['canvas','node','generate','--canvas-id',rec['canvas_id'],'--node-id',rec['node_id'],'--audio-intent','auto']);rec['status']='submitted'
   except Exception as e:rec.update(status='unknown',error=str(e))
   persist(rec);return rec
 if action in ('generation-status','download'):
  rec=retrieve(d['estimate_id'])
  def task_id(obj):
   if isinstance(obj,dict):
    for key in ('task_id','taskId'):
     if obj.get(key):return str(obj[key])
    for value in obj.values():
     found=task_id(value)
     if found:return found
   if isinstance(obj,list):
    for value in obj:
     found=task_id(value)
     if found:return found
  task=task_id(rec.get('submission',{}))
  if not task:raise ValueError('提交回执中未找到任务ID，请到纳逗原画布核对；不会重新提交')
  if action=='generation-status':
   rec['last_check']=run(['canvas','node','wait','--canvas-id',rec['canvas_id'],'--node-id',rec['node_id'],'--task-id',task,'--timeout','30s'],timeout=40);persist(rec);return rec['last_check']
  if rec.get('local_video'):return {'url':rec['local_video']}
  folder=RUNTIME/('download-'+rec['id']);folder.mkdir(exist_ok=True)
  rec['download']=run(['task','download','--canvas-id',rec['canvas_id'],'--task-id',task,'--output-dir',str(folder)],timeout=180);persist(rec)
  videos=[f for f in folder.rglob('*') if f.is_file() and f.suffix.lower() in ('.mp4','.webm','.mov')]
  if len(videos)!=1:raise ValueError('下载未返回唯一视频文件，请在原平台检查任务；下载回执已保存')
  target=RUNTIME/'media'/('nadou-'+rec['id']+videos[0].suffix.lower());target.parent.mkdir(exist_ok=True);shutil.copyfile(videos[0],target)
  rec['local_video']='/media/'+target.name;persist(rec);return {'url':rec['local_video']}
 if action=='wait':return run(['canvas','node','wait','--canvas-id',d['canvas_id'],'--node-id',d['node_id'],'--task-id',d['task_id'],'--timeout','30s'],timeout=40)
 raise ValueError('不支持的纳逗操作')
