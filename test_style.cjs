const fs=require('fs'),vm=require('vm'),assert=require('assert'),crypto=require('crypto');
const noop=()=>{},c={crypto,structuredClone,render:noop,bindPage:noop,canvasPage:noop,editAsset:noop,editShot:noop,save:noop,state:{title:'雨后的小店'}};vm.createContext(c);const js=fs.readFileSync('dist/studio.js','utf8');vm.runInContext(js.slice(0,js.lastIndexOf('refreshConfig();')),c);vm.runInContext(fs.readFileSync('dist/story-style.js','utf8'),c);
(async()=>{
 assert(c.projectStyle().tone.includes('治愈'));assert(c.projectStyle().visual.includes('米黄纸张'));
 const original=structuredClone(c.projectStyle()),custom={id:'custom',name:'水彩旅途',tone:'温暖',visual:'透明水彩',rhythm:'缓慢',avoid:'霓虹'};
 c.state.storyStyle=custom;let sent=[];c.api=async(path,p)=>{sent.push(p);return {status:'succeeded',result:{text:'ok',url:'/media/result.png'}}};
 await c.jobResult({},'image',{kind:'image',prompt:'主角在森林'});assert(sent[0].prompt.includes('透明水彩'));assert(!sent[0].prompt.includes('米黄纸张'));
 await c.jobResult({style:original},'image',{kind:'image',prompt:'主角'});assert(sent[1].prompt.includes('米黄纸张'));assert(!sent[1].prompt.includes('透明水彩'));
 await c.jobResult({},'voice',{kind:'audio',prompt:'你好'});assert.equal(sent[2].prompt,'你好');
 const existing={requests:{image:{id:'old',params:{kind:'image',prompt:'先前已提交的请求'}}}};await c.jobResult(existing,'image',{kind:'image',prompt:'新内容'});assert.equal(sent[3].prompt,'先前已提交的请求');
 console.log('PASS: healing default; custom style reaches image request; workflow style snapshot; spoken words unchanged; original request preserved');
})().catch(e=>{console.error(e);process.exit(1)});
