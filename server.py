"""Loopback-only production bridge. Secrets stay in process memory; never exported."""
import base64,hashlib,json,mimetypes,os,re,secrets,subprocess,sys,threading,time,uuid,urllib.request,urllib.error,urllib.parse
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'.runtime';RUNTIME.mkdir(exist_ok=True)
MEDIA=RUNTIME/'media';MEDIA.mkdir(exist_ok=True)
DIST=ROOT/'dist';LOCK=threading.RLock();TOKEN=secrets.token_urlsafe(32);KEYS={};JOBS={}
def load(path,default):
 try:return json.loads(path.read_text())
 except (OSError,ValueError):return default
def write(path,data):
 t=path.with_suffix('.tmp');t.write_text(json.dumps(data,ensure_ascii=False,indent=2));os.replace(t,path)
CONFIG=load(RUNTIME/'profiles.json',{'profiles':[],'defaults':{}})
for f in RUNTIME.glob('job-*.json'):
 j=load(f,{})
 if j.get('id'):
  if j.get('status')=='running':j.update(status='unknown',error='服务重启，原请求结果未知。请核对平台原任务，不能自动重试。')
  JOBS[j['id']]=j
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):raise ValueError('接口重定向已停止，请填写最终接口地址')
OPENER=urllib.request.build_opener(NoRedirect)
def clean_error(e):
 text=str(e)
 for key in KEYS.values():
  if key:text=text.replace(key,'[密钥已隐藏]')
 return text[:600]
def request(url,body=None,key='',method=None,binary=False):
 u=urllib.parse.urlparse(url)
 if u.scheme not in ('https','http') or not u.hostname or u.username or u.password:raise ValueError('接口需要有效的HTTP(S)地址')
 if u.scheme=='http' and u.hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('远程接口必须使用HTTPS')
 headers={'Accept':'application/json'}
 if key:headers['Authorization']='Bearer '+key
 if body is not None:headers['Content-Type']='application/json'
 req=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
 try:
  with OPENER.open(req,timeout=180) as r:
   raw=r.read(100*1024*1024+1)
   if len(raw)>100*1024*1024:raise ValueError('单个返回文件超过100MB')
   return (raw,r.headers.get_content_type()) if binary else json.loads(raw)
 except urllib.error.HTTPError as e:raise ValueError('模型接口返回 HTTP '+str(e.code)+'，请检查地址、模型和密钥')
def getpath(obj,path):
 for key in path.split('.') if path else []:
  obj=obj[int(key)] if isinstance(obj,list) else obj[key]
 return obj
def expand(obj,values):
 if isinstance(obj,dict):return {k:expand(v,values) for k,v in obj.items()}
 if isinstance(obj,list):return [expand(v,values) for v in obj]
 if isinstance(obj,str):
  if obj.startswith('{{') and obj.endswith('}}') and obj[2:-2] in values:return values[obj[2:-2]]
  for k,v in values.items():obj=obj.replace('{{'+k+'}}',str(v))
 return obj
def media_save(raw,mime,jobid):
 suffix={'audio/mpeg':'.mp3','audio/wav':'.wav','image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','video/mp4':'.mp4'}.get(mime,mimetypes.guess_extension(mime) or '.bin')
 name=jobid+suffix;(MEDIA/name).write_bytes(raw);return '/media/'+name

def reference_data(value):
 if not value:return value
 if value.startswith('data:'):return value
 if value.startswith('assets/'):
  path=(DIST/value).resolve();base=(DIST/'assets').resolve()
 elif value.startswith('/media/'):
  path=(RUNTIME/value.lstrip('/')).resolve();base=MEDIA.resolve()
 else:raise ValueError('参考图必须先导入本地工作台')
 if not path.is_relative_to(base) or not path.is_file():raise ValueError('参考图文件不存在')
 mime=mimetypes.guess_type(path.name)[0] or ''
 if not mime.startswith('image/'):raise ValueError('参考素材必须是图片')
 return 'data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode()

def generate(p,data,job):
 kind=data['kind'];prompt=data.get('prompt','');provider=p['provider']
 if provider=='nadou':
  raise ValueError('纳逗模型请使用画布“同步到纳逗”，在目标节点估价后提交；不会改为独立任务扣费。')
 values={'model':p['model'],'prompt':prompt,'input':prompt,'voice':data.get('voice') or p.get('voice',''),'image':reference_data(data.get('image','')),'references':[reference_data(x) for x in data.get('references',[])],'duration':data.get('duration',5),'ratio':data.get('ratio','16:9'),'resolution':data.get('resolution','480p')}
 if provider=='http':body=expand(p.get('body',{}),values)
 elif kind=='text':body={'model':p['model'],'messages':data.get('messages') or [{'role':'user','content':prompt}]}
 elif kind=='image':
  if data.get('references'):raise ValueError('当前OpenAI兼容文生图接口不接收参考图。请配置支持references的自定义图片接口，避免形象漂移。')
  body={'model':p['model'],'prompt':prompt,'n':1}
 elif kind=='audio':
  if not values['voice']:raise ValueError('该角色未配置确认后的voice_id')
  body={'model':p['model'],'input':prompt,'voice':values['voice'],'response_format':'mp3','speed':data.get('speed',1)}
 else:raise ValueError('视频请配置自定义HTTP接口或通过纳逗CLI生成')
 defaults={'text':'/chat/completions','image':'/images/generations','audio':'/audio/speech','video':''}
 path=p.get('path') or defaults[kind];url=p['base_url'].rstrip('/')+'/'+path.lstrip('/')
 if provider!='http' and kind=='audio':
  raw,mime=request(url,body,KEYS.get(p['id'],''),binary=True)
  if not mime.startswith('audio/'):raise ValueError('配音接口没有返回音频')
  return {'url':media_save(raw,mime,job['id'])}
 result=request(url,body,KEYS.get(p['id'],''))
 if provider=='http' and p.get('job_id_path'):
  remote=str(getpath(result,p['job_id_path']));job['remote_id']=remote;persist_job(job)
  poll=p.get('poll_path','').replace('{id}',urllib.parse.quote(remote,safe=''))
  if not poll:raise ValueError('异步接口未设置轮询路径；任务已提交，不能重新生成')
  for _ in range(180):
   time.sleep(3);result=request(p['base_url'].rstrip('/')+'/'+poll.lstrip('/'),key=KEYS.get(p['id'],''))
   status=str(getpath(result,p.get('status_path','status')))
   if status==p.get('success_status','succeeded'):break
   if status in ('failed','error','cancelled'):raise ValueError('平台任务失败：'+remote)
  else:raise TimeoutError('等待超时，保留原任务 '+remote+'，请在平台核对')
 if kind=='text':return {'text':str(getpath(result,p.get('result_path') or 'choices.0.message.content'))}
 if provider!='http' and kind=='image':
  item=result['data'][0]
  if item.get('b64_json'):return {'url':media_save(base64.b64decode(item['b64_json']),'image/png',job['id'])}
  location=item['url']
 else:location=getpath(result,p.get('result_path') or 'url')
 if isinstance(location,str) and location.startswith('data:'):
  header,encoded=location.split(',',1);mime=header[5:].split(';')[0];raw=base64.b64decode(encoded)
 else:raw,mime=request(str(location),binary=True)
 expected={'image':'image/','audio':'audio/','video':'video/'}[kind]
 if not mime.startswith(expected):raise ValueError('返回内容不是有效的'+kind+'媒体')
 return {'url':media_save(raw,mime,job['id'])}
def persist_job(job):
 with LOCK:write(RUNTIME/('job-'+job['id']+'.json'),job)
def run_job(job,p,data):
 try:
  result=generate(p,data,job);job.update(status='succeeded',result=result)
 except (TimeoutError,urllib.error.URLError) as e:job.update(status='unknown',error=clean_error(e))
 except Exception as e:job.update(status='failed',error=clean_error(e))
 finally:persist_job(job)

def submit(data):
 if not data.get('confirmed'):raise ValueError('请先确认本次发送内容与模型费用')
 ident=data.get('request_id','')
 if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',ident):raise ValueError('缺少有效请求ID')
 digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
 with LOCK:
  if ident in JOBS:
   if JOBS[ident]['fingerprint']!=digest:raise ValueError('同一请求ID不能更换内容')
   return JOBS[ident]
  p=next((p for p in CONFIG['profiles'] if p['id']==data.get('profile_id')),None)
  if not p or p['kind']!=data.get('kind'):raise ValueError('请配置并选择对应类型模型')
  job={'id':ident,'status':'running','kind':data['kind'],'profile_id':p['id'],'fingerprint':digest,'created_at':time.time()};JOBS[ident]=job;persist_job(job)
 threading.Thread(target=run_job,args=(job,p.copy(),data),daemon=True).start();return job
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(DIST),**kw)
 def send_head(self):
  self._video_remaining=None
  path=Path(self.translate_path(self.path))
  requested=self.headers.get('Range')
  if path.suffix.lower() not in ('.mp4','.webm','.mov') or not path.is_file() or not requested:return super().send_head()
  size=path.stat().st_size;m=re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
  if not m or not any(m.groups()):return self.send_error(416)
  start=int(m[1]) if m[1] else max(0,size-int(m[2]));end=min(size-1,int(m[2])) if m[1] and m[2] else size-1
  if start>=size or start>end:
   self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return None
  f=path.open('rb');f.seek(start);self._video_remaining=end-start+1
  self.send_response(206);self.send_header('Content-Type',self.guess_type(str(path)));self.send_header('Accept-Ranges','bytes');self.send_header('Content-Range',f'bytes {start}-{end}/{size}');self.send_header('Content-Length',str(self._video_remaining));self.end_headers();return f
 def copyfile(self,source,outputfile):
  if getattr(self,'_video_remaining',None) is None:return super().copyfile(source,outputfile)
  remaining=self._video_remaining
  try:
   while remaining:
    chunk=source.read(min(65536,remaining))
    if not chunk:break
    outputfile.write(chunk);remaining-=len(chunk)
  except (BrokenPipeError,ConnectionResetError):pass
 def log_message(self,*a):pass
 def allowed(self):
  host=self.headers.get('Host','');origin=self.headers.get('Origin')
  return host in ('127.0.0.1:8765','localhost:8765') and (not origin or origin in ('http://127.0.0.1:8765','http://localhost:8765'))
 def json_out(self,obj,status=200):
  raw=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  if not self.allowed():return self.json_out({'error':'仅允许本机访问'},403)
  try:
   path=urllib.parse.urlparse(self.path).path
   if path=='/api/session':return self.json_out({'token':TOKEN,'version':2})
   if path=='/api/config':return self.json_out({**CONFIG,'profiles':[{**p,'has_key':bool(KEYS.get(p['id']))} for p in CONFIG['profiles']]})
   if path.startswith('/api/jobs/'):
    j=JOBS.get(path.rsplit('/',1)[1]);return self.json_out(j or {'error':'任务不存在'},200 if j else 404)
   if path=='/api/nadou/status':
    from nadou_bridge import status
    return self.json_out(status())
   if path.startswith('/media/'):
    name=path.rsplit('/',1)[1]
    if not re.fullmatch(r'[\w-]+\.[a-z0-9]+',name) or not (MEDIA/name).is_file():return self.send_error(404)
    self.path='/'+name;self.directory=str(MEDIA);return super().do_GET()
   if path.startswith('/api/'):return self.json_out({'error':'接口不存在'},404)
   return super().do_GET()
  except Exception as e:return self.json_out({'error':clean_error(e)},400)
 def do_POST(self):
  if not self.allowed() or self.headers.get('X-Studio-Token')!=TOKEN:return self.json_out({'error':'页面连接已失效，请刷新'},403)
  try:
   size=int(self.headers.get('Content-Length',0))
   if size>60*1024*1024:raise ValueError('请求过大')
   data=json.loads(self.rfile.read(size));path=self.path
   if path=='/api/config':
    profiles=[]
    for p in data.get('profiles',[]):
     if p.get('kind') not in ('text','image','audio','video') or p.get('provider') not in ('openai','http','nadou'):raise ValueError('模型类型无效')
     ident=p.get('id') or str(uuid.uuid4());p['id']=ident
     if p.get('key'):KEYS[ident]=p['key']
     if p.get('clear_key'):KEYS.pop(ident,None)
     profiles.append({k:v for k,v in p.items() if k not in ('key','has_key','clear_key')})
    with LOCK:CONFIG.update(profiles=profiles,defaults=data.get('defaults',CONFIG.get('defaults',{})));write(RUNTIME/'profiles.json',CONFIG)
    return self.json_out({'saved':True})
   if path=='/api/generate':return self.json_out(submit(data),202)
   if path=='/api/test':
    p=next(p for p in CONFIG['profiles'] if p['id']==data['profile_id'])
    if p['provider']=='nadou':
     from nadou_bridge import status
     return self.json_out(status())
    request(p['base_url'].rstrip('/')+'/models',key=KEYS.get(p['id'],''));return self.json_out({'ok':True,'message':'模型列表接口可访问；不代表生成能力已验证'})
   if path.startswith('/api/nadou/'):
    from nadou_bridge import dispatch
    return self.json_out(dispatch(path.removeprefix('/api/nadou/'),data))
   return self.json_out({'error':'接口不存在'},404)
  except Exception as e:return self.json_out({'error':clean_error(e)},400)
def main():
 server=ThreadingHTTPServer(('127.0.0.1',8765),Handler);print('万象工作台 http://127.0.0.1:8765 · 本地模型桥接已启动',flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
if __name__=='__main__':main()
