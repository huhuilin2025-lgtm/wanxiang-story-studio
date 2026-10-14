import tempfile,unittest,time
from pathlib import Path
import server as s
import nadou_bridge as n
class BridgeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();s.RUNTIME=Path(self.tmp.name);s.MEDIA=s.RUNTIME/'media';s.MEDIA.mkdir();s.JOBS.clear();s.CONFIG={'profiles':[{'id':'test-text','provider':'openai','kind':'text','model':'unit','base_url':'https://example.invalid/v1'}]};self.old=s.request;self.oldrun=n.run;n.RUNTIME=s.RUNTIME
 def tearDown(self):s.request=self.old;n.run=self.oldrun;self.tmp.cleanup()
 def test_once(self):
  calls=[]
  def req(*a,**kw):calls.append(a);return {'choices':[{'message':{'content':'结果'}}]}
  s.request=req;d={'confirmed':True,'request_id':'test-request-001','profile_id':'test-text','kind':'text','prompt':'故事'};j=s.submit(d)
  for _ in range(100):
   if j['status']!='running':break
   time.sleep(.01)
  self.assertEqual(j['result']['text'],'结果');s.submit(d);self.assertEqual(len(calls),1)
  with self.assertRaises(ValueError):s.submit({**d,'prompt':'不同内容'})
 def test_confirm(self):
  with self.assertRaises(ValueError):s.submit({'request_id':'test-12345'})
 def test_type(self):
  with self.assertRaises(ValueError):s.submit({'confirmed':True,'request_id':'test-12345','profile_id':'test-text','kind':'video'})
 def test_refs_not_dropped(self):
  with self.assertRaisesRegex(ValueError,'不接收参考图'):s.generate({'id':'t','provider':'openai','model':'t'},{'kind':'image','references':['data:image/png;base64,AA==']},{'id':'test'})
 def test_local_refs(self):
  with self.assertRaises(ValueError):s.reference_data('assets/../../server.py')
  self.assertTrue(s.reference_data('data:image/png;base64,aGVsbG8=').startswith('data:image/png;base64,'))
 def test_custom(self):
  s.request=lambda *a,**kw:{'output':{'text':'定制结果'}}
  result=s.generate({'id':'custom','provider':'http','model':'m','base_url':'https://example.invalid','path':'/run','body':{'prompt':'{{prompt}}'},'result_path':'output.text'},{'kind':'text','prompt':'分析'},{'id':'c'})
  self.assertEqual(result['text'],'定制结果')
 def test_audio(self):
  s.request=lambda *a,**kw:(b'unit-test','audio/mpeg')
  result=s.generate({'id':'a','provider':'openai','model':'t','base_url':'https://example.invalid'},{'kind':'audio','prompt':'你好','voice':'confirmed'},{'id':'audio-unit'})
  self.assertEqual(result['url'],'/media/audio-unit.mp3')
 def test_timeout(self):
  s.request=lambda *a,**kw:(_ for _ in ()).throw(TimeoutError('timeout'))
  j={'id':'timeout','status':'running'};s.run_job(j,s.CONFIG['profiles'][0],{'kind':'text','prompt':'test'});self.assertEqual(j['status'],'unknown')
 def test_graph_hash(self):self.assertEqual(n.graph_hash({'data':{'nodes':[]},'meta':{'request_id':'a'}}),n.graph_hash({'data':{'nodes':[]},'meta':{'request_id':'b'}}))
 def test_graph_hash_ignores_observation_fields(self):
  self.assertEqual(n.graph_hash({'data':{'nodes':[],'edges':[],'observed_at':'a','backend_request_id':'1'}}),n.graph_hash({'data':{'nodes':[],'edges':[],'observed_at':'b','backend_request_id':'2'}}))
 def test_sync_plan_read_only(self):
  calls=[]
  def run(args,*a,**kw):calls.append(args);return {'data':{'schema':{'defaults':{'ratio':'16:9'}}}} if args[0]=='model' else {'data':{'nodes':[]}}
  n.run=run;p=n.dispatch('plan',{'canvas_id':'real-id','model':'real-model','shots':[{'id':'s01','image':'data:image/png;base64,aGVsbG8='}]});self.assertEqual(p['shots'],1);self.assertEqual(len(calls),2);self.assertFalse(any('mutate' in a or 'generate' in a for a in calls))
if __name__=='__main__':unittest.main()
