const fs=require('fs'),vm=require('vm'),assert=require('assert'),crypto=require('crypto');
const noop=()=>{},c={crypto,structuredClone,render:noop,bindPage:noop,canvasPage:noop,editAsset:noop,editShot:noop,save:noop};vm.createContext(c);let src=fs.readFileSync('dist/studio.js','utf8');vm.runInContext(src.slice(0,src.lastIndexOf('refreshConfig();')),c);c.render=noop;
(async()=>{
 const plan={assets:[{name:'新角色·初登场',kind:'人物',description:'蓝衣',traits:'谨慎',bio:'旅人'}],shots:[{id:'s1',title:'抵达',duration:5,description:'走进森林',dialogue:'',assetNames:['新角色·初登场']}]};
 c.state={assets:[],canvas:{},production:{e1:{id:'r1',status:'running',step:'analyze',mode:'rebuild',models:{text:'t',image:'i'},pending:[],requests:{},completed:0}}};const e={id:'e1',shots:[],script:'走进森林'};const calls=[];c.jobResult=async(r,k,p)=>{calls.push(k);return k==='analysis'?{text:JSON.stringify(plan)}:{url:'/media/'+k+'.png'}};
 await c.runWorkflow(e);assert.equal(c.state.production.e1.status,'awaiting_assets');assert.equal(e.shots.length,0);assert(!calls.some(k=>k.startsWith('shot-')));assert.equal(c.state.assets.length,0);
 const a=c.state.production.e1.pending[0];a.approval='已确认';c.state.assets.push(structuredClone(a));await c.runWorkflow(e);assert.equal(c.state.production.e1.status,'complete');assert.equal(e.shots.length,1);assert.equal(e.shots[0].assetIds[0],a.id);assert.equal(c.state.canvas.e1.length,4);assert.equal(calls.filter(k=>k==='analysis').length,1);
 assert.throws(()=>c.parsePlan(JSON.stringify({...plan,shots:[{...plan.shots[0],assetNames:['不存在']}]})),/未建档/);
 c.state.canvas.e1[0].x=919;c.ensureCanvas(e);assert.equal(c.state.canvas.e1[0].x,919);
 // Changed appearance cannot reuse approved identity by copying name/id.
 c.state.assets=[{id:'old',name:plan.assets[0].name,description:'红衣',approval:'已确认'}];plan.assets[0].existingId='old';c.state.production.e2={step:'analyze',mode:'rebuild',models:{},completed:0};const e2={id:'e2',shots:[],script:''};await c.runWorkflow(e2);assert.equal(c.state.production.e2.status,'awaiting_assets');assert.notEqual(c.state.production.e2.pending[0].id,'old');
 console.log('PASS: new assets block shots; approval resumes; no duplicate analysis; asset integrity; layout preservation; costume change requires approval');
})().catch(e=>{console.error(e);process.exit(1)});
