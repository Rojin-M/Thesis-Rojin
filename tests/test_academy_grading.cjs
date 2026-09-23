'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const G=require('../academy/grading.js');
const D=JSON.parse(fs.readFileSync(path.join(__dirname,'../academy/curriculum.js'),'utf8').replace(/^window\.ACADEMY_CURRICULUM\s*=\s*/,'').replace(/;\s*$/,''));
const questions=[...D.modules.flatMap(m=>m.quiz),...D.units.flatMap(u=>u.exam)];
const number={id:'n',type:'number',answer:0,tolerance:0,unit:'value'};
const single={id:'s',type:'single',options:['a','b','c'],answer:1};
const multi={id:'m',type:'multi',options:['a','b','c','d'],answer:[1,3]};

test('blank, whitespace and coercible non-numbers cannot receive a numerical point',()=>{
  for(const value of ['', ' ',null,undefined,false,true,[],{},'NaN','Infinity','0x0','0 ppm']){
    assert.equal(G.answered(number,value),false,String(value));
    assert.equal(G.correct(number,value),false,String(value));
  }
  assert.equal(G.correct(number,'0'),true);
});
test('signed decimal and scientific notation are accepted; units stay explicit',()=>{
  assert.equal(G.numeric(' -1.33e-2 '),-.0133);
  assert.equal(G.numeric('.5'),.5);
  assert.equal(G.numeric('1,000'),null);
  assert.equal(G.numeric('25%'),null);
});
test('tolerance accepts a numerical boundary and rejects a materially larger error',()=>{
  const q={...number,answer:1.4,tolerance:.01};
  assert.equal(G.correct(q,'1.41'),true);
  assert.equal(G.correct(q,'1.39'),true);
  assert.equal(G.correct(q,'1.411'),false);
});
test('single choices must identify an existing canonical option',()=>{
  assert.equal(G.correct(single,1),true);
  for(const a of [0,2,3,-1,1.5,'1',undefined])assert.equal(G.correct(single,a),false);
});
test('multi-select requires the exact set with no partial credit or duplicate workaround',()=>{
  assert.equal(G.correct(multi,[3,1]),true);
  for(const a of [[],[1],[1,2,3],[1,1,3],[1,4],['1',3]])assert.equal(G.correct(multi,a),false);
});
test('incomplete attempts return no score and name missing questions',()=>{
  const result=G.grade([number,single,multi],{n:'0',s:1,m:[]});
  assert.equal(result.complete,false);assert.deepEqual(result.missing,['m']);assert.equal(result.score,undefined);
});
test('mixed assessment score is correct against a hand-checked answer set',()=>{
  const r=G.grade([number,single,multi],{n:'0',s:0,m:[3,1]});
  assert.equal(r.score,2);assert.equal(r.total,3);assert.equal(r.needed,3);assert.equal(r.passed,false);
});
test('six-question lessons need five correct; previous partial attempts cannot be combined',()=>{
  const qs=Array.from({length:6},(_,i)=>({...single,id:'q'+i}));
  const four=Object.fromEntries(qs.map((q,i)=>[q.id,i<4?1:0]));
  assert.equal(G.grade(qs,four).passed,false);
  const five={...four,q4:1};assert.equal(G.grade(qs,five).passed,true);
  assert.equal(G.grade(qs,five).letter,'B');
});
test('unit and final pass boundaries are six of eight and twenty-two of twenty-seven',()=>{
  const quiz=(n,right,t)=>{const qs=Array.from({length:n},(_,i)=>({...single,id:'q'+i}));return G.grade(qs,Object.fromEntries(qs.map((q,i)=>[q.id,i<right?1:0])),t);};
  assert.equal(quiz(8,5,.75).passed,false);assert.equal(quiz(8,6,.75).passed,true);
  assert.equal(quiz(27,21,.8).passed,false);assert.equal(quiz(27,22,.8).passed,true);
});
test('all authored question keys grade correctly and a nearby wrong answer fails',()=>{
  for(const q of questions){
    const answer=q.type==='number'?String(q.answer):q.answer;
    assert.equal(G.correct(q,answer),true,q.id);
    const wrong=q.type==='number'?String(q.answer+Math.max(1,q.tolerance*2)):
      q.type==='single'?(q.answer+1)%q.options.length:q.answer.slice(1);
    assert.equal(G.correct(q,wrong),false,q.id);
  }
});
test('shuffle preserves canonical answer identities and never mutates authored order',()=>{
  const input=[0,1,2,3], copy=input.slice(), out=G.shuffle(input,G.rng(42));
  assert.deepEqual(input,copy);assert.deepEqual(out.slice().sort(),input);
  assert.deepEqual(out,G.shuffle(input,G.rng(42)));
  assert.equal(G.correct(single,out.find(v=>v===1)),true);
});
test('teaching seeds reproduce streams while distinct seeds give different starts',()=>{
  const draw=seed=>{const r=G.rng(seed);return Array.from({length:10},r);};
  assert.deepEqual(draw(42),draw(42));assert.notDeepEqual(draw(42),draw(43));
  assert.ok(draw(42).every(v=>v>=0&&v<1));
});
test('toy gradient update reproduces the hand calculation',()=>{
  const r=G.trainToy(1,.1,1);
  assert.equal(r[0].prediction,2);assert.equal(r[0].loss,2);assert.equal(r[0].gradient,-4);
  assert.equal(r[1].weight,1.4);assert.ok(Math.abs(r[1].loss-.72)<1e-12);
});
test('toy learning converges with the stable rate and diverges at the displayed unstable rate',()=>{
  assert.ok(G.trainToy(1,.1,20).at(-1).loss<1e-7);
  assert.ok(G.trainToy(1,.6,20).at(-1).loss>2);
});
test('attention is normalized, stable for large scores and matches the worked example',()=>{
  const w=G.softmax([Math.log(3),0]);assert.ok(Math.abs(w[0]-.75)<1e-12);
  assert.ok(Math.abs(w[0]*2+w[1]*10-4)<1e-12);
  assert.deepEqual(G.softmax([1000,1000]),[.5,.5]);
});
