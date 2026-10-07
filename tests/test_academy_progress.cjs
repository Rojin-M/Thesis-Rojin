'use strict';
// Execute the real application and grader. Only browser DOM/storage APIs are faked;
// actual Chromium layout/interaction checks are separate from these regressions.
const test=require('node:test'), assert=require('node:assert/strict');
const fs=require('node:fs'), path=require('node:path'), vm=require('node:vm');
const G=require('../academy/grading.js');
const root=path.join(__dirname,'../academy');
const D=JSON.parse(fs.readFileSync(path.join(root,'curriculum.js'),'utf8').replace(/^window\.ACADEMY_CURRICULUM\s*=\s*/,'').replace(/;\s*$/,''));
const KEY='exoplanet-academy:v2', clone=x=>JSON.parse(JSON.stringify(x));
function fixture(){
  const qs=D.modules[0].quiz, ids=qs.map(q=>q.id);
  const answers=Object.fromEntries(qs.map(q=>[q.id,q.type==='number'?String(q.answer):q.answer]));
  const wrong={...answers,[qs[0].id]:String(qs[0].answer+100)};
  const at='2026-09-23T18:00:00.000Z';
  return {version:2,revision:'2026-09-23.1',theme:'light',last:'light',records:{'lesson/light':{
    best:{ids,answers,at,result:G.grade(qs,answers,.8)},last:{ids,answers:wrong,at,result:G.grade(qs,wrong,.8)},attempts:2}},
    review:{[ids[0]]:{wrong:true,streak:0,due:123456}},history:[{scope:'lesson/light',at,score:5,total:6}],
    drafts:{'lesson/missions':{ids:D.modules[2].quiz.map(q=>q.id),answers:{'missions-q1':'0'},seed:42}}};
}
function app(raw,extension=null){
  const storage=new Map([[KEY,JSON.stringify(raw)],['exoplanet-academy:v1','{"notes":"keep"}']]);
  const elements=new Map(), downloads=[], callbacks={};
  const node=()=>({innerHTML:'',textContent:'',dataset:{},listeners:{},attributes:{},classList:{add(){},remove(){},toggle(){return true;}},
    addEventListener(k,fn){this.listeners[k]=fn;},setAttribute(k,v){this.attributes[k]=v;},focus(){},scrollIntoView(){},
    querySelector(s){if(s==='h1')return {textContent:this.innerHTML.match(/<h1[^>]*>(.*?)<\/h1>/s)?.[1]||'',focus(){}};return get(s);},
    querySelectorAll(){return [];},click(){downloads.push(this);},remove(){}});
  const get=s=>{if(!elements.has(s))elements.set(s,node());return elements.get(s);};
  const location={hash:'#dashboard'}, body=node();body.append=()=>{};
  const document={body,documentElement:{dataset:{}},querySelector:get,getElementById:id=>get('#'+id),createElement:node,addEventListener(){},getElementsByName(){return [{value:'',checked:false}];}};
  const blobs=new Map();let n=0;
  const context={window:{ACADEMY_CURRICULUM:{...clone(D),researchExtension:extension},AcademyGrade:G,AcademyLabs:{render(){return '';},init(){},names:{}},addEventListener(k,fn){callbacks[k]=fn;},scrollTo(){},confirm(){return true;}},document,location,
    localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
    Blob,URL:{createObjectURL(blob){const key='blob:'+ ++n;blobs.set(key,blob);return key;},revokeObjectURL(){}},setTimeout(){return 1;},clearTimeout(){},navigator:{}};
  vm.runInNewContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),context);
  return {storage,get,context,go(hash){location.hash='#'+hash;callbacks.hashchange();},
    async export(){await get('#content').listeners.click({target:{closest(){return {dataset:{action:'export'}};}}});return JSON.parse(await blobs.get(downloads.at(-1).href).text());},
    async import(value){this.go('grades');await get('#import-progress').listeners.change({target:{files:[{size:1000,async text(){return JSON.stringify(value);}}]}});}};
}
test('content refresh reload preserves mastery, best/latest, drafts, review, history, theme and legacy',async()=>{
  const before=fixture(), a=app(before);
  assert.equal(D.revision,before.revision);assert.notEqual(D.contentRevision,D.revision);
  assert.match(a.get('#course-progress').innerHTML,/1 \/ 36/);
  assert.equal(a.context.document.documentElement.dataset.theme,'light');
  for(const route of ['project','library','grades','truth','roadmap','dashboard'])a.go(route);
  assert.deepEqual(await a.export(),before);
  assert.equal(a.storage.get('exoplanet-academy:v1'),'{"notes":"keep"}');
  assert.equal([...a.storage.keys()].some(k=>k.includes(':archive:')),false);
  assert.doesNotMatch(a.get('#content').innerHTML,/edition changed/);
  const reload=app(await a.export());assert.deepEqual(await reload.export(),before);
});
test('matching-edition imports and exports round trip and forged cached grades are regraded',async()=>{
  const before=fixture(), a=app(before), tampered=clone(before);
  tampered.records['lesson/light'].last.result.score=6;
  await a.import(tampered);
  assert.deepEqual(await a.export(),before);
  const invalid={...before,revision:'different-edition'};await a.import(invalid);
  assert.match(a.get('#import-status').textContent,/Import failed/);
  assert.deepEqual(await a.export(),before);
});
test('optional extension hooks stay outside assessment selection and preserve learning records',async()=>{
  const before=fixture(), extension=D.researchExtension;
  const a=app(before,extension);
  assert.match(a.get('#primary-nav').innerHTML,/#research-updates/);
  a.go('research-updates');assert.match(a.get('#content').innerHTML,/adds no graded questions or completion requirements/);
  for(const c of extension.cards){a.go('research-updates/'+c.id);assert.ok(a.get('#content').innerHTML.includes(`id="research-${c.id}"`));assert.match(a.get('#primary-nav').innerHTML, /href="#research-updates" aria-current="page"/);}
  const change=a.get('#workflow-choice').listeners.change;
  change({target:{value:'broker'}});assert.match(a.get('#workflow-view').innerHTML,/separate observing program/);
  change({target:{value:'watcher'}});assert.match(a.get('#workflow-view').innerHTML,/does not command a telescope/);assert.match(a.get('#workflow-view').innerHTML,/#project/);
  change({target:{value:'btsbot'}});assert.match(a.get('#workflow-view').innerHTML,/SEDM/);
  assert.deepEqual(await a.export(),before);
  a.go('lesson/capstone');assert.match(a.get('#content').innerHTML,/#research-updates/);assert.match(a.get('#content').innerHTML,/#final/);
  const after=await a.export();assert.deepEqual({...after,last:before.last},before);
  a.go('final');
  const exported=await a.export();assert.equal(exported.drafts.final.ids.length,27);
  assert.equal(new Set(exported.drafts.final.ids).size,27);
  for(const unit of D.units){const lids=D.modules.filter(m=>m.unit===unit.id).map(m=>m.id);const bank=[...D.modules.flatMap(m=>m.quiz),...D.units.flatMap(u=>u.exam)];assert.equal(exported.drafts.final.ids.filter(id=>lids.includes(bank.find(q=>q.id===id).lesson)).length,3);}
  assert.equal(D.modules.length,36);assert.equal(D.units.length,9);
});
test('research reading desk dates and primary citations lead back to the authored tour',()=>{
  const a=app(fixture(),D.researchExtension);a.go('library');const html=a.get('#content').innerHTML;
  for(const c of D.researchExtension.cards)assert.ok(html.includes(`#research-updates/${c.id}`));
  for(const text of ['Submitted 2025-01-30','Event 2024-05-28','Published 2026-02-25','Documentation updated 2026-07-03','Preprint','White paper'.toLowerCase()])assert.ok(html.includes(text),text);
  for(const text of ['Published 2026-01-07','Journal issue 2026-04','Published 2025-05-29','Publication record'])assert.ok(html.includes(text),text);
  a.go('research-updates');const tour=a.get('#content').innerHTML;
  assert.doesNotMatch(tour,/href="\.\.\//);
  const external=[...tour.matchAll(/<a href="https:[^>]+>/g)];assert.ok(external.length>=16);
  for(const [link] of external)assert.match(link,/rel="noopener noreferrer"/);
});
test('no optional content produces no broken navigation link',()=>{
  const a=app(fixture());assert.doesNotMatch(a.get('#primary-nav').innerHTML,/#research-updates/);
  a.go('lesson/capstone');assert.doesNotMatch(a.get('#content').innerHTML,/#research-updates/);
});
test('project navigation renders cohort tables, caveats and copyable paths without parent links',()=>{
  const a=app(fixture());a.go('project');const html=a.get('#content').innerHTML;
  for(const [key,id] of [['deployment','deployment'],['classification','classification'],['detectors','detectors'],['next','next-experiments'],['sources','provenance']]){
    assert.ok(html.includes(`data-scroll="${id}"`),key);assert.ok(html.includes(`id="${id}"`),key);
  }
  for(const text of ['13/14','12/14','17/90','44/330','21/99','53/326','0.171893','not_calibrated_for_blind_search','not a survey astrophysical false-positive rate','Proposed work'])assert.ok(html.includes(text),text);
  assert.equal((html.match(/<caption>/g)||[]).length,6);
  assert.doesNotMatch(html,/href="\.\.\//);
  a.go('library');assert.match(a.get('#content').innerHTML,/access dates shown per source/);assert.match(a.get('#content').innerHTML,/#project/);
});
