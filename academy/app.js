(function () {
  'use strict';
  const D=window.ACADEMY_CURRICULUM, G=window.AcademyGrade, Labs=window.AcademyLabs;
  const KEY='exoplanet-academy:v2', OLD_KEY='exoplanet-academy:v1';
  const $=s=>document.querySelector(s);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const modules=new Map(D.modules.map(m=>[m.id,m])), units=new Map(D.units.map(u=>[u.id,u]));
  const bank=new Map([...D.modules.flatMap(m=>m.quiz),...D.units.flatMap(u=>u.exam)].map(q=>[q.id,q]));
  const content=$('#content');
  const fresh=()=>({version:2,revision:D.revision,theme:'dark',last:'light',records:{},review:{},history:[],drafts:{}});
  let storageOK=true, legacy=null, notice='', activeQuiz=null;
  function scopeInfo(scope) {
    const [type,id]=String(scope).split('/');
    if(type==='lesson' && modules.has(id)) return {type,id,title:modules.get(id).title,threshold:.8};
    if(type==='exam' && units.has(id)) return {type,id,title:units.get(id).title+' · unit exam',threshold:.75};
    if(scope==='final') return {type:'final',title:'Final assessment',threshold:.8};
    if(['practice','review'].includes(scope)) return {type:scope,title:scope==='review'?'Mistakes & spaced review':'Mixed practice',threshold:.8};
    return null;
  }
  function validIds(scope,ids) {
    const info=scopeInfo(scope);
    if(!info||!Array.isArray(ids)||!ids.length||ids.length>40||new Set(ids).size!==ids.length||ids.some(id=>!bank.has(id))) return false;
    if(info.type==='lesson') return ids.length===6 && modules.get(info.id).quiz.every(q=>ids.includes(q.id));
    if(info.type==='exam') {
      const u=units.get(info.id), ms=D.modules.filter(m=>m.unit===u.id);
      return ids.length===8 && u.exam.every(q=>ids.includes(q.id)) && ms.every(m=>ids.filter(id=>m.quiz.some(q=>q.id===id)).length===1);
    }
    if(info.type==='final') return ids.length===D.units.length*3 && D.units.every(u=>ids.filter(id=>modules.get(bank.get(id).lesson).unit===u.id).length===3);
    return ids.length<=10;
  }
  function sanitizeAnswers(ids,answers) {
    const clean={};
    if(!answers||typeof answers!=='object'||Array.isArray(answers)) return clean;
    ids.forEach(id=>{
      const q=bank.get(id), a=answers[id];
      if(q.type==='number' && ['string','number'].includes(typeof a) && String(a).length<=60) clean[id]=String(a);
      if(q.type==='single' && Number.isInteger(a)) clean[id]=a;
      if(q.type==='multi' && Array.isArray(a) && a.length<=q.options.length) clean[id]=a.filter(Number.isInteger);
    });
    return clean;
  }
  function parseAttempt(scope,a) {
    if(!a||!validIds(scope,a.ids)) return null;
    const answers=sanitizeAnswers(a.ids,a.answers), result=G.grade(a.ids.map(id=>bank.get(id)),answers,scopeInfo(scope).threshold);
    if(!result.complete) return null;
    return {ids:a.ids,answers,at:typeof a.at==='string'&&Number.isFinite(Date.parse(a.at))?a.at:new Date().toISOString(),result};
  }
  function normalize(raw) {
    const out=fresh();
    if(!raw||raw.version!==2||raw.revision!==D.revision) return out;
    out.theme=raw.theme==='light'?'light':'dark';
    out.last=modules.has(raw.last)?raw.last:'light';
    Object.entries(raw.records||{}).slice(0,60).forEach(([scope,r])=>{
      if(!scopeInfo(scope)||!r||typeof r!=='object') return;
      const best=parseAttempt(scope,r.best), last=parseAttempt(scope,r.last);
      if(best&&last) out.records[scope]={best:last.result.percent>best.result.percent?last:best,last,attempts:Math.max(1,Math.min(100000,Math.floor(Number(r.attempts)||1)))};
    });
    Object.entries(raw.review||{}).forEach(([id,r])=>{
      if(bank.has(id)&&r&&typeof r==='object') out.review[id]={wrong:r.wrong===true,streak:Math.max(0,Math.min(3,Math.floor(Number(r.streak)||0))),due:Math.max(0,Math.min(Date.now()+14*86400000,Number(r.due)||0))};
    });
    Object.entries(raw.drafts||{}).slice(0,60).forEach(([scope,d])=>{
      if(d&&validIds(scope,d.ids)) out.drafts[scope]={ids:d.ids,answers:sanitizeAnswers(d.ids,d.answers),seed:Number(d.seed)>>>0};
    });
    out.history=Array.isArray(raw.history)?raw.history.filter(h=>h&&scopeInfo(h.scope)&&Number.isFinite(h.score)&&Number.isFinite(h.total)&&h.total>0&&h.score>=0&&h.score<=h.total&&typeof h.at==='string'&&Number.isFinite(Date.parse(h.at))).slice(-30):[];
    return out;
  }
  let state=fresh();
  try {
    const old=localStorage.getItem(OLD_KEY);if(old) legacy=old;
    const raw=localStorage.getItem(KEY);
    if(raw) {
      const parsed=JSON.parse(raw);
      if(parsed.revision!==D.revision) {
        localStorage.setItem(KEY+':archive:'+String(parsed.revision||'unknown'),raw);
        notice='The course edition changed. Earlier grades were archived separately; the new assessments start fresh.';
      } else state=normalize(parsed);
    }
  } catch (_) {storageOK=false;notice='Saved progress could not be read. The course still works; export your new progress before leaving.';}
  function save() {
    try {localStorage.setItem(KEY,JSON.stringify(state));storageOK=true;}catch(_){storageOK=false;}
    $('#save-status').textContent=storageOK?'Saved in this browser':'Not saved · export progress';
  }
  function toast(message) {
    const el=$('#toast');el.textContent=message;el.classList.add('visible');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove('visible'),4000);
  }
  const passed=scope=>!!state.records[scope]?.best.result.passed;
  const mastered=()=>D.modules.filter(m=>passed('lesson/'+m.id));
  const nextLesson=()=>D.modules.find(m=>!passed('lesson/'+m.id))||modules.get(state.last)||D.modules[0];
  const badge=scope=>{const r=state.records[scope];return r?`<span class="badge ${r.best.result.passed?'success':''}">${r.best.result.passed?'✓ ':''}${r.best.result.score}/${r.best.result.total}</span>`:'<span class="badge">Not graded</span>';};
  const button=(href,label,secondary=false)=>`<a class="button${secondary?' secondary':''}" href="${esc(href)}">${esc(label)}</a>`;
  const header=(eye,title,lead)=>`<header class="page-header"><p class="eyebrow">${esc(eye)}</p><h1 tabindex="-1">${esc(title)}</h1><p class="lead">${esc(lead)}</p></header>`;
  function nav(route) {
    const n=mastered().length;
    $('#course-progress').innerHTML=`<div class="progress-label"><strong>${n} / ${D.modules.length}</strong><span>lessons mastered</span></div><progress max="${D.modules.length}" value="${n}" aria-label="Lessons passed"></progress><a href="#grades">View grades & backups →</a>`;
    const m=modules.get(route.split('/')[1]);
    const activeUnit=(route.startsWith('lesson/')||route.startsWith('check/'))&&m?m.unit:route.startsWith('unit/')?route.split('/')[1]:null;
    let html='<div class="nav-group">';
    [['dashboard','Course overview'],['labs','Interactive lab'],['practice','Practice & exams'],['grades','Grades & progress'],['project','Your project'],['library','Research reading desk'],['glossary','Glossary']].forEach(([id,label])=>{html+=`<a href="#${id}" ${route===id?'aria-current="page"':''}>${label}</a>`;});
    if(D.researchExtension)html+=`<a href="#research-updates" ${(route==='research-updates'||route.startsWith('research-updates/'))?'aria-current="page"':''}>Optional research extension</a>`;
    html+='</div><p class="nav-heading">Your learning path</p><div class="nav-units">';
    D.units.forEach((u,i)=>{const ms=D.modules.filter(m=>m.unit===u.id),count=ms.filter(m=>passed('lesson/'+m.id)).length;html+=`<a href="#unit/${u.id}" ${activeUnit===u.id?'aria-current="page"':''}><span class="nav-num">${String(i+1).padStart(2,'0')}</span><span>${esc(u.title)}<small>${count} / 4 lessons mastered</small></span></a>`;});
    $('#primary-nav').innerHTML=html+'</div>';
  }
  function lessonRow(m) {
    return `<a class="lesson-row" href="#lesson/${m.id}"><span class="lesson-number">${String(m.order).padStart(2,'0')}</span><span><strong>${esc(m.title)}</strong><small>${esc(m.objectives[0])}</small></span>${badge('lesson/'+m.id)}<span aria-hidden="true">↗</span></a>`;
  }
  function overview() {
    const next=nextLesson(), n=mastered().length;
    let html=`<section class="hero"><div><p class="eyebrow">A course built around your research</p><h1 tabindex="-1">From a dip in the light<br>to a defensible idea.</h1><p class="lead">Understand the sky. Learn how models learn. Read current research. Then make sense of your own pipeline and test what should come next.</p><div class="button-row">${button('#lesson/'+next.id,n?'Continue your course →':'Start lesson 01 →')}${button('#unit/learning','Go to ML foundations',true)}</div><p class="muted">Beginner-friendly sequence · local grading · no paid API calls</p></div><div class="hero-orbit" aria-hidden="true"><div class="star"></div><div class="orbit"><i></i></div><div class="orbit second"></div><span>Observe → explain → test</span></div></section>`;
    if(notice)html+=`<p class="notice">${esc(notice)}</p>`;
    if(legacy)html+='<p class="notice">Your earlier Academy notes and progress are preserved. The redesigned course has new assessments, so old completion ticks do not count as new grades. <button class="text-button" data-action="legacy">Export the previous edition</button></p>';
    html+=`<div class="stat-grid"><div><strong>36</strong><span>guided lessons</span></div><div><strong>12</strong><span>dedicated ML lessons</span></div><div><strong>252</strong><span>graded questions</span></div><div><strong>9</strong><span>interactive experiments</span></div></div>`;
    html+='<section class="course-guide"><div><p class="eyebrow">How to study</p><h2>Build the idea, then test it.</h2><p>Start with the explanation, then work through the example one step at a time. For a calculation, check what each symbol means and keep the units beside the numbers. Try the interactive experiment when there is one. Each lesson ends with a recap, a common mistake to watch for, and six graded questions with explanations.</p><p>A lesson passes at 5/6; a unit exam at 6/8; the final at 22/27. If an answer is wrong, follow its explanation back to the lesson and try again. Your best grade is kept.</p></div><div><h3>Take the time you need</h3><p>Allow roughly 20–30 hours for a first pass with practice. The lesson times are guides, not deadlines. Start at lesson 1 if the astronomy is new; use ML foundations to focus on how models learn. The technical ideas build on one another, so revisit an earlier lesson whenever a term is unfamiliar. Reading papers and reproducing analyses takes additional time. Exams reuse the learning bank: these grades track practice, not a formal qualification.</p></div></section>';
    html+='<div class="section-heading"><div><p class="eyebrow">Nine units · foundations to research</p><h2>Your course map</h2></div><label class="search-label">Find a lesson<input id="course-search" type="search" placeholder="Try seeds, CNN, probability…"></label></div><p id="search-count" class="muted" role="status"></p><div class="unit-grid">';
    D.units.forEach((u,i)=>{const ms=D.modules.filter(m=>m.unit===u.id);html+=`<section class="unit-card" data-unit-card><div class="unit-top"><span class="unit-index">UNIT ${String(i+1).padStart(2,'0')}</span>${badge('exam/'+u.id)}</div><h2><a href="#unit/${u.id}">${esc(u.title)}</a></h2><p>${esc(u.subtitle)}</p><div>${ms.map(m=>`<div data-lesson-search="${m.id}">${lessonRow(m)}</div>`).join('')}</div><a class="unit-exam-link" href="#exam/${u.id}">Take unit exam · 8 questions →</a></section>`;});
    html+='</div><section class="callout"><h2>Follow the model journey</h2><p>Start with the shared Kepler CNN, test transfer and expert models, then compare the fresh classifier audit and detector recovery. The project map labels what ran on 28 September; the live Research site shows each candidate’s current score identity.</p>'+button('#project','Open the evidence map',true)+researchLink()+'</section>';
    content.innerHTML=html;
    $('#course-search').addEventListener('input',e=>{
      const term=e.target.value.trim().toLowerCase();let count=0;
      content.querySelectorAll('[data-lesson-search]').forEach(el=>{const m=modules.get(el.dataset.lessonSearch);const text=[m.title,m.hook,...m.objectives,...m.sections.map(s=>s.title+' '+s.paragraphs.join(' '))].join(' ').toLowerCase();el.hidden=!text.includes(term);if(!el.hidden)count++;});
      content.querySelectorAll('[data-unit-card]').forEach(el=>{el.hidden=![...el.querySelectorAll('[data-lesson-search]')].some(row=>!row.hidden);});
      $('#search-count').textContent=term?`${count} matching lesson${count===1?'':'s'}`:'';
    });
  }
  function unitPage(id) {
    const u=units.get(id);if(!u)return notFound();
    const ms=D.modules.filter(m=>m.unit===id),index=D.units.indexOf(u);
    content.innerHTML=header(`Unit ${index+1} / ${D.units.length}`,u.title,u.subtitle)+`<section class="callout"><p class="eyebrow">By the end of this unit</p><p>${esc(u.outcome)}</p><p class="muted">Four lessons · about 35 minutes each including practice · prerequisites: ${index?esc(D.units[index-1].title):'curiosity and basic arithmetic'}.</p></section><div class="lesson-list">${ms.map(lessonRow).join('')}</div><section class="assessment-card"><h2>Unit exam</h2><p>Eight questions: one drawn from each lesson and four additional applied cases. All answers are graded locally. Pass at 6/8; retakes are welcome.</p><div class="button-row">${button('#exam/'+id,'Start unit exam')}${badge('exam/'+id)}</div></section>`;
  }
  function sourceDates(s) {
    return [['submitted','Submitted'],['revised','Revised'],['earlyOnline','Early online'],['published','Published'],['issueDate','Journal issue'],['updated','Documentation updated'],['eventDate','Event'],['version','Version']].filter(([key])=>s[key]).map(([key,label])=>label+' '+s[key]).join(' · ');
  }
  function publicationLink(s) {
    return s.publicationUrl?`<a class="source-version" href="${esc(s.publicationUrl)}" target="_blank" rel="noopener noreferrer">Publication record ↗</a>`:'';
  }
  function sourceLinks(ids) {
    return ids.map(id=>D.sources.find(s=>s.id===id)).filter(Boolean).map(s=>`<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)} ↗</a><small>${esc(s.year)} · ${esc(s.status)}${s.checked?' · source checked '+esc(s.checked):''}</small>${sourceDates(s)?`<small>${esc(sourceDates(s))}</small>`:''}${s.fullText?`<a class="source-version" href="${esc(s.fullText)}" target="_blank" rel="noopener noreferrer">Read inspected full text ↗</a>`:''}${publicationLink(s)}</li>`).join('');
  }
  function codeBlock(code) {return `<div class="code-block"><button class="copy-code" data-action="copy-code">Copy</button><pre><code>${esc(code)}</code></pre></div>`;}
  function lessonPage(id) {
    const m=modules.get(id);if(!m)return notFound();
    state.last=id;save();const u=units.get(m.unit),index=D.modules.indexOf(m),previous=D.modules[index-1],next=D.modules[index+1];
    let html=`<div class="reading"><a class="back-link" href="#unit/${u.id}">← ${esc(u.title)}</a>`+header(`Lesson ${String(m.order).padStart(2,'0')} / 36 · about ${m.minutes} minutes`,m.title,m.hook);
    html+=`<div class="lesson-meta">${badge('lesson/'+id)}<span>${m.quiz.length} graded questions</span>${m.lab?'<span>Interactive experiment</span>':''}</div>`;
    if(previous&&!passed('lesson/'+previous.id))html+=`<p class="prerequisite">This builds on <a href="#lesson/${previous.id}">${esc(previous.title)}</a>. You can continue now and revisit that lesson if an idea feels unfamiliar.</p>`;
    html+=`<section class="objectives"><h2>What you’ll be able to do</h2><ul>${m.objectives.map(o=>'<li>'+esc(o)+'</li>').join('')}</ul></section><nav class="lesson-jumps" aria-label="Jump within lesson"><button data-scroll="explanation">Learn</button><button data-scroll="example">Worked example</button>${m.lab?'<button data-scroll="experiment">Try it</button>':''}<button data-scroll="checkpoint">Get graded</button></nav><div id="explanation">`;
    m.sections.forEach((s,i)=>{html+=`<section class="lesson-section"><span class="step-label">${String(i+1).padStart(2,'0')}</span><h2>${esc(s.title)}</h2>${s.paragraphs.map(p=>'<p>'+esc(p)+'</p>').join('')}</section>`;});
    html+=`</div><section id="example" class="worked-example"><p class="eyebrow">Let’s work through it</p><h2>${esc(m.example.title)}</h2><p>Follow the steps, then compare your interpretation with the explanation below.</p><ol>${m.example.steps.map(s=>'<li>'+esc(s)+'</li>').join('')}</ol><details><summary>What does this result tell us?</summary><p>${esc(m.example.answer)}</p></details></section>`;
    if(m.lab)html+=`<div id="experiment">${Labs.render(m.lab)}</div>`;
    if(m.code)html+='<section class="code-section"><h2>Read and run the calculation</h2><p class="muted">Use a Python session for Python examples; use your project terminal for shell commands. Code is shown for study and is not executed by this page.</p>'+codeBlock(m.code)+'</section>';
    html+=`<section class="project-note"><p class="eyebrow">In your project · snapshot ${D.checked}</p><p>${esc(m.project)}</p></section>`;
    html+=`<section class="lesson-recap card"><h2>Take this with you</h2><p>${esc(m.takeaway)}</p><h3>A common mistake to watch for</h3><p>${esc(m.pitfall)}</p></section>`;
    html+=`<section id="checkpoint" class="assessment-card"><p class="eyebrow">Check your understanding</p><h2>Put the idea into practice</h2><p>Answer six questions using the ideas you just studied. Choose answers or enter a number where asked; every answer is graded for you. Submit to see your score and an explanation for each question. Pass at 5/6. You can return to the lesson and retake the check as often as you need.</p><div class="button-row">${button('#check/'+id,state.drafts['lesson/'+id]?'Resume your check':'Start graded check')}${badge('lesson/'+id)}</div></section>`;
    if(m.sources.length)html+=`<section class="sources"><h2>Go to the primary sources</h2><p class="muted">Read these after the lesson. External links open a new tab; publication and live documentation may change.</p><ul>${sourceLinks(m.sources)}</ul></section>`;
    else html+='<p class="muted">This lesson draws on the local repository and its dated result artifacts. See the <a href="#project">project evidence map</a>.</p>';
    if(D.researchExtension&&['frontier','representation','uncertainty','pixels','injections'].includes(m.id))html+=`<aside class="callout"><h2>See this idea in astronomy research</h2><p>Follow the optional tour from model inputs to measured evidence and limitations.</p>${researchLink()}</aside>`;
    html+='<div class="lesson-footer">'+(previous?button('#lesson/'+previous.id,'← Previous lesson',true):button('#dashboard','← Course overview',true))+(next?button('#lesson/'+next.id,'Next lesson →'):button('#final','Take the final assessment →'))+'</div>'+(!next?researchLink():'')+'</div>';
    content.innerHTML=html;Labs.init(content);
  }
  function practicePage() {
    const wrong=Object.entries(state.review).filter(([,r])=>r.wrong).length;
    const due=Object.entries(state.review).filter(([,r])=>r.due<=Date.now()).length;
    content.innerHTML=header('Practice without an essay','Test your understanding','Every answer is graded against an explicit key or numerical tolerance. Questions ask you to calculate, diagnose and choose the next scientific action.')+
      `<div class="practice-grid"><section class="card"><p class="eyebrow">Target the gaps</p><h2>Mistakes & spaced review</h2><p>${wrong} unresolved mistakes · ${due} questions due. Correct answers return after 1, 3 and then 7 days. Missed questions are immediately eligible.</p>${button('#review','Review up to 10 questions')}</section><section class="card"><p class="eyebrow">Mix the subjects</p><h2>Ten-question practice</h2><p>Draw from the full course bank. This diagnostic can expose gaps; a mixed-practice score does not mark individual lessons mastered.</p>${button('#mixed','Start mixed practice',true)}</section><section class="card"><p class="eyebrow">Across the full course</p><h2>Final assessment</h2><p>27 questions, three per unit. Pass at 22/27. Complete the lesson checks and unit exams too for full course mastery. The bank is visible for learning; this is not a proctored credential.</p>${button('#final','Take the final assessment',true)} ${badge('final')}</section></div><h2>Unit exams</h2><div class="exam-list">${D.units.map((u,i)=>`<a href="#exam/${u.id}"><span>${i+1}. ${esc(u.title)}</span>${badge('exam/'+u.id)}</a>`).join('')}</div>`;
  }
  function chooseQuestions(scope,random) {
    const info=scopeInfo(scope);
    if(info.type==='lesson')return modules.get(info.id).quiz;
    if(info.type==='exam')return [...units.get(info.id).exam,...D.modules.filter(m=>m.unit===info.id).map(m=>G.shuffle(m.quiz,random)[0])];
    if(info.type==='final')return D.units.flatMap(u=>G.shuffle([...u.exam,...D.modules.filter(m=>m.unit===u.id).flatMap(m=>m.quiz)],random).slice(0,3));
    if(info.type==='review') {
      return Object.entries(state.review).filter(([,r])=>r.wrong||r.due<=Date.now()).sort((a,b)=>Number(b[1].wrong)-Number(a[1].wrong)||a[1].due-b[1].due).slice(0,10).map(([id])=>bank.get(id));
    }
    return G.shuffle([...bank.values()],random).slice(0,10);
  }
  function quizPage(scope,retake=false) {
    const info=scopeInfo(scope);if(!info)return notFound();
    let draft=!retake&&state.drafts[scope];
    if(!draft) {
      const seed=Date.now()>>>0,random=G.rng(seed),qs=G.shuffle(chooseQuestions(scope,random),random);
      if(!qs.length){activeQuiz=null;content.innerHTML=header('Review queue','Nothing is due right now','Take a lesson check or mixed practice to build your review queue. Correct answers return for practice after 1, 3 and 7 days.')+button('#practice','Choose another assessment');return;}
      draft={ids:qs.map(q=>q.id),answers:{},seed};state.drafts[scope]=draft;save();
    }
    const qs=draft.ids.map(id=>bank.get(id));activeQuiz={scope,qs,seed:draft.seed,graded:false};
    const random=G.rng(draft.seed),needed=Math.ceil(qs.length*info.threshold);
    let html='<div class="reading">'+header(info.type==='lesson'?'Lesson checkpoint':info.type==='exam'?'Unit assessment':'Graded practice',info.title,`${qs.length} questions · ${needed}/${qs.length} to pass · answers saved as you go`);
    if(info.type==='lesson')html+=`<p><a href="#lesson/${info.id}">← Back to the lesson</a></p>`;
    html+='<p class="notice">Single choice: select one. Multiple choice: select all correct options; no partial credit. Numerical answers: enter only the number in the displayed unit. Each question is worth one point. Explanations appear after submission; retakes use the same learning bank with shuffled choices.</p><div id="quiz-result" tabindex="-1" role="status"></div><form id="quiz-form" novalidate>';
    qs.forEach((q,i)=>{
      html+=`<fieldset class="question" id="question-${q.id}" data-question="${q.id}"><legend><span class="question-num">${String(i+1).padStart(2,'0')}</span>${esc(q.prompt)}</legend><p class="question-kind">${q.type==='single'?'Choose one':q.type==='multi'?'Select all correct options · exact match required':`Number in ${esc(q.unit)} · tolerance ±${q.tolerance}`}</p>`;
      if(q.type==='number')html+=`<label class="numeric-answer" for="answer-${q.id}">Your answer (${esc(q.unit)})<input id="answer-${q.id}" name="${q.id}" type="text" inputmode="decimal" autocomplete="off" maxlength="60" value="${esc(draft.answers[q.id]??'')}" placeholder="Enter a number" aria-describedby="feedback-${q.id}"></label>`;
      else html+='<div class="options">'+G.shuffle(q.options.map((text,index)=>({text,index})),random).map(({text,index})=>`<label class="option"><input type="${q.type==='multi'?'checkbox':'radio'}" name="${q.id}" value="${index}" ${q.type==='multi'?(draft.answers[q.id]||[]).includes(index)?'checked':'':draft.answers[q.id]===index?'checked':''}><span>${esc(text)}</span></label>`).join('')+'</div>';
      html+=`<div class="feedback" id="feedback-${q.id}"></div></fieldset>`;
    });
    html+='<div class="submit-bar"><span id="answered-count"></span><button class="button" type="submit">Submit & get my grade</button></div></form><div id="quiz-next"></div></div>';
    content.innerHTML=html;
    $('#quiz-form').addEventListener('change',stashDraft);$('#quiz-form').addEventListener('input',stashDraft);$('#quiz-form').addEventListener('submit',submitQuiz);updateAnswered();
  }
  function readAnswers() {
    const answers={};
    if(!activeQuiz)return answers;
    activeQuiz.qs.forEach(q=>{
      const els=[...document.getElementsByName(q.id)];
      if(q.type==='number')answers[q.id]=els[0].value;
      else if(q.type==='multi')answers[q.id]=els.filter(e=>e.checked).map(e=>Number(e.value));
      else {const checked=els.find(e=>e.checked);if(checked)answers[q.id]=Number(checked.value);}
    });return answers;
  }
  function updateAnswered() {if(!activeQuiz||!$('#answered-count'))return;const a=readAnswers();$('#answered-count').textContent=`${activeQuiz.qs.filter(q=>G.answered(q,a[q.id])).length} / ${activeQuiz.qs.length} answered`;}
  function stashDraft(){if(!activeQuiz||activeQuiz.graded)return;state.drafts[activeQuiz.scope]={ids:activeQuiz.qs.map(q=>q.id),seed:activeQuiz.seed,answers:readAnswers()};save();updateAnswered();}
  function submitQuiz(event) {
    event.preventDefault();if(!activeQuiz||activeQuiz.graded)return;
    const {scope,qs}=activeQuiz,answers=readAnswers(),info=scopeInfo(scope),result=G.grade(qs,answers,info.threshold);
    if(!result.complete){$('#quiz-result').innerHTML=`<p class="notice warning">Answer all questions with valid responses before grading. ${result.missing.length} still need attention; blank numerical answers do not count as zero.</p>`;const target=$('#question-'+result.missing[0]);target.scrollIntoView({block:'center'});target.querySelector('input').focus({preventScroll:true});return;}
    activeQuiz.graded=true;
    const at=new Date().toISOString(),attempt={ids:qs.map(q=>q.id),answers,at,result},old=state.records[scope];
    state.records[scope]={best:old&&old.best.result.percent>result.percent?old.best:attempt,last:attempt,attempts:(old?.attempts||0)+1};
    result.results.forEach(r=>{
      const previous=state.review[r.id],streak=r.correct?Math.min(3,(previous?.streak||0)+1):0;
      state.review[r.id]={wrong:!r.correct,streak,due:Date.now()+(r.correct?[1,3,7][streak-1]*86400000:0)};
      const q=bank.get(r.id),field=$('#question-'+r.id);field.classList.add(r.correct?'correct':'incorrect');field.disabled=true;
      $('#feedback-'+r.id).innerHTML=`<strong>${r.correct?'✓ Correct':'✕ Not quite'}</strong>${!r.correct?`<p><b>Expected:</b> ${esc(G.answerText(q))}</p>`:''}<p>${esc(q.explanation)}</p><a href="#lesson/${q.lesson}">Review: ${esc(modules.get(q.lesson).title)} →</a>`;
    });
    delete state.drafts[scope];state.history.push({scope,at,score:result.score,total:result.total});state.history=state.history.slice(-30);save();nav(currentRoute());
    $('#quiz-form button[type="submit"]').disabled=true;
    $('#quiz-result').innerHTML=`<section class="grade-result ${result.passed?'passed':''}"><div class="grade-letter">${result.letter}</div><div><p class="eyebrow">${result.passed?'Passed':'Keep practicing'}</p><h2>${result.score} / ${result.total} · ${result.percent.toFixed(1)}%</h2><p>${result.needed} correct needed. Best: ${state.records[scope].best.result.score}/${result.total} · Attempt ${state.records[scope].attempts}. ${info.type==='lesson'?(result.passed?'Lesson mastery recorded.':'Use the explanations below, then try the full check again.'):'This grade is recorded separately from lesson mastery.'}</p></div></section>`;
    let next='';if(info.type==='lesson'){const m=modules.get(info.id),following=D.modules[D.modules.indexOf(m)+1];next=following?button('#lesson/'+following.id,'Next lesson →'):button('#final','Final assessment →');}
    $('#quiz-next').innerHTML=`<div class="button-row"><button class="button secondary" data-action="retake">Try a fresh attempt</button>${button('#review','Review mistakes',true)}${next}${button('#grades','View gradebook',true)}${info.type==='final'?researchLink():''}</div>`;
    $('#quiz-result').scrollIntoView({block:'start'});$('#quiz-result').focus({preventScroll:true});
  }
  function gradesPage() {
    const n=mastered().length,exams=D.units.filter(u=>passed('exam/'+u.id)).length,complete=n===36&&exams===9&&passed('final');
    let html=header('Your evidence of learning','Grades & progress',complete?'You passed every lesson, every unit exam and the final assessment. Continue with reproduction and supervised research practice.':'Reading is freely accessible. Mastery is earned by passing the corresponding assessment; there is no manual “mark complete” button.');
    html+=`<div class="stat-grid"><div><strong>${n}/36</strong><span>lesson checks passed</span></div><div><strong>${exams}/9</strong><span>unit exams passed</span></div><div><strong>${passed('final')?'Passed':'Pending'}</strong><span>final assessment</span></div><div><strong>${Object.values(state.review).filter(r=>r.wrong).length}</strong><span>mistakes to revisit</span></div></div>`;
    html+='<section class="card"><h2>Keep your learning record</h2><p>Progress belongs to this browser and address. Export it before changing browser, clearing site data or switching forwarded ports. The JSON includes grades, attempts, review timing and unfinished answers. Imports must match this course edition and are regraded locally.</p><div class="button-row"><button class="button" data-action="export">Export progress JSON</button><label class="button secondary import-button">Import progress<input id="import-progress" type="file" accept=".json,application/json"></label>'+(legacy?'<button class="button secondary" data-action="legacy">Export previous Academy notes</button>':'')+'<button class="text-button danger" data-action="reset">Reset this course’s progress</button></div><p id="import-status" role="status"></p></section>';
    html+='<div class="table-wrap"><table><caption>Lesson grades · equal-weight objective questions</caption><thead><tr><th>Lesson</th><th>Best</th><th>Latest</th><th>Attempts</th></tr></thead><tbody>';
    D.modules.forEach(m=>{const r=state.records['lesson/'+m.id];html+=`<tr><td><a href="#lesson/${m.id}">${m.order}. ${esc(m.title)}</a></td><td>${badge('lesson/'+m.id)}</td><td>${r?`${r.last.result.score}/${r.last.result.total}`:'—'}</td><td>${r?.attempts||0}</td></tr>`;});
    html+='</tbody></table></div><h2>Unit and final grades</h2><div class="exam-list">'+D.units.map(u=>`<a href="#exam/${u.id}"><span>${esc(u.title)}</span>${badge('exam/'+u.id)}</a>`).join('')+`<a href="#final"><span>Final assessment</span>${badge('final')}</a></div>`;
    if(state.history.length)html+='<details class="history"><summary>Recent assessment attempts</summary><ul>'+state.history.slice().reverse().map(h=>`<li>${esc(new Date(h.at).toLocaleString())} · ${esc(scopeInfo(h.scope).title)} · ${h.score}/${h.total}</li>`).join('')+'</ul></details>';
    content.innerHTML=html;
    $('#import-progress').addEventListener('change',async e=>{
      const f=e.target.files[0];if(!f)return;
      try{
        if(f.size>5*1024*1024)throw Error('The file exceeds the 5 MB progress limit.');
        const raw=JSON.parse(await f.text());
        if(raw.version!==2||raw.revision!==D.revision||!raw.records||typeof raw.records!=='object'||Array.isArray(raw.records))throw Error('Use an export from this course edition ('+D.revision+'). Earlier Academy notes remain available separately.');
        const imported=normalize(raw);
        if(Object.keys(raw.records).length!==Object.keys(imported.records).length)throw Error('The file contains an invalid assessment record; nothing was replaced.');
        if(!window.confirm('Replace this browser’s course progress with the imported record? Export your current record first if you want to keep both.'))return;
        state=imported;save();applyTheme();route();toast('Progress imported and assessment answers regraded.');
      }catch(err){$('#import-status').textContent='Import failed: '+err.message;e.target.value='';}
    });
  }
  function libraryPage() {
    content.innerHTML=header('Primary sources · access dates shown per source','The research reading desk','Read by task and evidence, not by headline accuracy. Start with the course explanations, then use these sources to deepen and challenge them.')+`<p class="notice">This is a curated reading path, not an exhaustive “best model” leaderboard. 2026 preprints are marked explicitly; their reported results have not been independently reproduced here. ${button('#lesson/frontier','Read the guided comparison',true)} ${button('#project','Read current project evidence',true)} ${researchLink()}</p><div class="library-grid">${D.sources.map(s=>`<article class="paper-card"><p class="eyebrow">${esc(s.year)} · ${esc(s.status)}</p><h2><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)} ↗</a></h2><p>${esc(s.takeaway)}</p>${s.evidenceType?`<p class="muted">Evidence: ${esc(s.evidenceType)}</p>`:''}${sourceDates(s)?`<p class="muted">${esc(sourceDates(s))}</p>`:''}${publicationLink(s)}<p class="muted">${s.checked?'Source checked '+esc(s.checked):'See the linked record for dates'}${s.accessNote?' · '+esc(s.accessNote):''}</p><div class="paper-lessons">${researchSourceLinks(s.id)}${D.modules.filter(m=>m.sources.includes(s.id)).slice(0,3).map(m=>`<a href="#lesson/${m.id}">${esc(m.title)}</a>`).join('')}</div></article>`).join('')}</div>`;
  }
  function glossaryPage() {
    content.innerHTML=header('Definitions with a route back to understanding','Your working vocabulary','Each term links to a lesson that explains the mechanism and tests your understanding.')+'<label class="search-label glossary-search">Find a term<input id="glossary-search" type="search" placeholder="Gradient, DANN, ephemeris…"></label><p id="glossary-count" role="status" class="muted"></p><dl class="glossary">'+D.glossary.slice().sort((a,b)=>a.term.localeCompare(b.term)).map(g=>`<div data-term="${esc((g.term+' '+g.meaning).toLowerCase())}"><dt>${esc(g.term)}</dt><dd>${esc(g.meaning)} <a href="#lesson/${g.lesson}">Learn it →</a></dd></div>`).join('')+'</dl>';
    $('#glossary-search').addEventListener('input',e=>{const term=e.target.value.toLowerCase();let n=0;content.querySelectorAll('[data-term]').forEach(el=>{el.hidden=!el.dataset.term.includes(term);if(!el.hidden)n++;});$('#glossary-count').textContent=`${n} matching terms`;});
  }
  function labsPage() {
    content.innerHTML=header('See the mechanism change','Interactive lab','Nine small experiments run locally. They teach a formula or mechanism; they do not train a research model or evaluate real telescope data.')+'<div class="lab-index">'+Object.entries(Labs.names).map(([id,name])=>`<button class="chip" data-lab-select="${id}">${esc(name)}</button>`).join('')+'</div><div id="chosen-lab">'+Labs.render('gradient')+'</div>';
    Labs.init(content);
  }
  function evidenceTable(caption,heads,rows) {
    return `<div class="table-wrap evidence-table" role="region" aria-label="${esc(caption)}" tabindex="0"><table><caption>${esc(caption)}</caption><thead><tr>${heads.map(h=>`<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>'<tr>'+row.map((v,i)=>i?`<td>${esc(v)}</td>`:`<th scope="row">${esc(v)}</th>`).join('')+'</tr>').join('')}</tbody></table></div>`;
  }
  function evidencePaths(rows) {
    return '<ul class="evidence-list">'+rows.map(([label,path])=>`<li><div><strong>${esc(label)}</strong><code>${esc(path)}</code></div><button class="text-button" data-copy="${esc(path)}">Copy path</button></li>`).join('')+'</ul>';
  }
  function projectPage() {
    const P=D.project, deploy=P.deployment, watcher=P.watcher, H=P.historical_dann, C=P.reused_classifier, F=P.fresh_classifier;
    const labels={tess_only:'TESS only',kepler_only:'Fresh Kepler only',fine_tuned:'Kepler → TESS fine-tuning',pooled:'Pooled',dann:'Supervised DANN',crossfit_nonlinear:'Nonlinear eleven-expert stack',stellar_variability:'Variability expert',v4_static_stack:'Static v4 stack',crossfit_supermodel:'Nonlinear eleven-expert stack',v4_static:'Static v4 stack',v2:'Neural v2',v3:'Neural v3',bls:'BLS',tls:'TLS',v3_original:'Original v3 · 0.86',v3_calibrated:'Calibrated v3 · 0.90',single_event:'Single-event search',hybrid:'Hybrid (rejected)',bls_exact:'Exact-boundary BLS',tls_exact:'Exact-boundary TLS'};
    const fixed=(n,d=6)=>Number(n).toFixed(d), fraction=(n,total)=>`${n}/${total} (${fixed(100*n/total,1)}%)`;
    let html=header('Repository evidence · checked '+P.checked,'The project, end to end','The deployed scorer, candidate comparisons and research-only event detectors answer different questions. No experiment here establishes a universal winner to deploy.');
    html+='<nav class="lesson-jumps" aria-label="Project evidence sections">'+[['deployment','Deployed watcher'],['classification','Candidate classification'],['detectors','Event recovery'],['next-experiments','Next experiments'],['provenance','Evidence paths']].map(([id,label])=>`<button data-scroll="${id}">${label}</button>`).join('')+'</nav>';
    html+='<div class="project-stages">'+P.stages.map((s,i)=>`<a href="#lesson/${s[2]}" class="stage"><span>${i+1}</span><div><h2>${esc(s[0])}</h2><p>${esc(s[1])}</p></div><b aria-hidden="true">↗</b></a>`).join('')+'</div>';
    html+=`<section id="deployment" class="card evidence-section"><p class="eyebrow">Deployed · saved evidence checked ${esc(P.checked)}</p><h2>The frozen Kepler CNN remains authoritative</h2><p><strong>${esc(deploy.model_name)}</strong> supplies <code>model_score</code> through <code>FrozenScorer</code>. Its sigmoid output is a ranking score, not a planet-confirmation probability: <code>${esc(deploy.calibration)}</code>.</p><p>The bounded archival pilot had <strong>${watcher.selected_target_count} selected targets</strong>, a six-hour configured interval and at most ${watcher.max_products_per_cycle} products per cycle. A full selection budget does not mean complete archive coverage. The two fixed controls belong to the 23 September setup.</p><p>Comparison workers append experimental scores. The Transformer, nonlinear stack, v3 localizer and recovery hybrid have not replaced this scorer. This static page does not poll the live database.</p><details><summary>Input contract, checkpoint identity and dates</summary><p>200 global bins, 100 local bins and seven scalars; 907 flat features; frozen Kepler TRAIN normalization. A saved source-validation F1 threshold near 0.785 is provenance, not a blind-search gate.</p><p>Latest completed score inspected: <time>${esc(deploy.latest_completed_score_at)}</time>. Watcher scope captured: <time>${esc(watcher.as_of_utc)}</time>. A September 28 check is not a newly triggered September 28 score.</p>${evidencePaths([['Checkpoint',deploy.checkpoint_path],['Checkpoint SHA256',deploy.checkpoint_sha256],['Normalizer',deploy.normalizer_path],['Normalizer SHA256',deploy.normalizer_sha256],['Authoritative scorer','scripts/research/scoring.py']])}</details></section>`;
    html+=`<section id="classification" class="evidence-section"><h2>Candidate classification: compare within a cohort</h2><p>These methods rank already prepared, labeled candidates. The physical experts use known catalog ephemerides. AP/AUC measure ranking; accuracy uses threshold 0.5. None measures blind event-search recovery.</p><article class="card"><h3>Historical adaptation pilot · 23 September</h3>${evidenceTable(`${H.audit_rows} audit rows / ${H.audit_host_groups} groups · 3 seeds per arm · ${H.updates_per_fit} updates per fit`,['Approach','Mean AP','Seed sample SD'],['tess_only','kepler_only','fine_tuned','pooled','dann'].map(k=>[labels[k],fixed(H.methods[k].mean,4),fixed(H.methods[k].sd,4)]))}<p>Fine-tuning led this short pilot; DANN benefit was not demonstrated. All 15 fits completed, but convergence was not established. The audit came from a reused validation pool. Seed SD is not an uncertainty interval for a planet probability. The fresh Kepler arm is distinct from the older deployed CNN.</p><p>The historical comparison-inference check covered 44 proposals: 17 real controls and 27 synthetic/transformed controls, not 44 discoveries.</p></article>`;
    html+=`<article class="card"><h3>Reused audit · nonlinear stacking</h3>${evidenceTable(`${C.audit_rows} rows: ${C.positive} positive / ${C.negative} negative · report ${C.generated_at.slice(0,10)}`,['Method','AP','ROC AUC'],Object.entries(C.methods).map(([k,m])=>[labels[k],fixed(m.average_precision),fixed(m.roc_auc)]))}<p>The nonlinear stack leads this reused development audit. Cross-fitting does not undo earlier consultation of that audit, so this is not independent confirmation.</p><details><summary>How the eleven experts are combined</summary><p>Five CNN/DANN regimes, Transformer, transit morphology, stellar variability, TLS, aperture photometry and difference-image localization provide complementary evidence. Each of 538 out-of-fold training predictions comes from an expert that did not train on that host. Separate sets contain 162 selection rows, 81 calibration rows and 82 audit rows.</p><p>Selection chose trees with at most seven leaves, L2 regularization 10 and a 0.5 blend with the static v4 prior. Model selection, calibration and evaluation have different roles.</p>${button('#lesson/transfer','Learn the expert mechanisms',true)} ${button('#lesson/splits','Learn cross-fitting',true)}</details></article>`;
    html+=`<article class="card"><h3>Fresh frozen audit · ${F.completed_at.slice(0,10)}</h3><p><strong>${F.registered_candidates} registered → ${F.accepted_candidates} evaluated.</strong> ${F.acquisition.rejection_reasons.no_public_120s_product} lacked public native 120-second SPOC products. All 14 available passed unchanged preparation; this is availability selection, not 281 preprocessing failures.</p>${evidenceTable(`${F.accepted_candidates} candidates: ${F.positive} positive / ${F.negative} negative · fixed weights and calibration`,['Method','AP','ROC AUC','Brier','Correct at 0.5','Brier treatment'],Object.entries(F.methods).map(([k,m])=>[labels[k],fixed(m.average_precision),fixed(m.roc_auc),fixed(m.brier),fraction(m.correct_at_0_5,m.n),m.calibration]))}<p>Static v4 ranks all positives above all negatives but misses two at 0.5; nonlinear misses one. Better ranking and better fixed-threshold accuracy can belong to different models. Only three positives and coverage-selected catalog labels make this a small independent check, not a general superiority result.</p><p>${esc(F.calibration_caveat)}</p><p>The stored paired AP bootstrap compares nonlinear against variability, not static v4. No weights or thresholds were tuned here, and nothing was deployed.</p>${button('#lesson/metrics','Work through ranking versus accuracy',true)}</article></section>`;
    html+='<section id="detectors" class="evidence-section"><h2>Event recovery: injected signals, not new planets</h2><p>A neural localizer scans light curves and pixels for events. BLS/TLS test a strongest periodic hypothesis from the same injected aperture sums; their search capabilities differ. Count incremental one-to-one event matches within half the true duration, after subtracting matches already present in the original observation. All registered hosts remain in the denominator.</p>';
    const history=P.continuous_history;
    html+=`<details class="card"><summary>Historical trapezoidal audit · different protocol</summary>${evidenceTable('Reused 79-host / 276-event trapezoidal audit · historical, checked '+P.checked,['Method','Recovered hosts','Recovered events','Inverted alerts / 27 exposure-days'],['v2','v3'].map(k=>[labels[k],fraction(history[k].hosts,79),fraction(history[k].events,276),fixed(history[k].control_rate_rounded,3)]))}<p>${esc(history.limits)}</p><p>These rates are rounded historical values. Do not plot them as a measured trend against the later physical studies.</p></details>`;
    for(const [key,title,order] of [['physical_benchmark','Original physical audit',['v2','v3','bls','tls']],['fresh_recovery','Fresh recovery study',['v3_original','v3_calibrated','single_event','hybrid','bls_exact','tls_exact']]]) {
      const e=P[key];
      html+=`<article class="card"><h3>${title} · ${e.completed_at.slice(0,10)}</h3><p>${e.registered_hosts} registered hosts; ${e.observable_hosts} with observable injections; ${e.injected_events} injected events. Threshold calibration uses ${e.calibration_hosts} separate hosts. Mean control budget: at most 1 inverted alert per 27 exposure-days.</p>${evidenceTable(`${title}: incremental recovery and control burden`,['Method','Hosts recovered','Events recovered','Inverted alerts','Alerts / 27 exposure-days'],order.map(k=>{const m=e.methods[k];return [labels[k],fraction(m.incremental_hosts,e.registered_hosts),fraction(m.incremental_events,e.injected_events),m.inverted_alerts,fixed(m.inverted_alerts_per_27_days)];}))}`;
      if(key==='physical_benchmark')html+='<p>v3 fails the budget here (1.368977). TLS equals its host count and recovers more events. The v3–v2 host difference has paired exact p=0.21875 without multiplicity correction. Original BLS used a conservative coarse threshold of 100; low recovery here does not establish intrinsic algorithm failure.</p>';
      else html+=`<p>Raising v3 from 0.86 to 0.90 reduces controls by ${fixed(100*e.derived_comparison.inverted_control_relative_reduction,3)}% (27 → 14) over identical exposure, while losing five events. <strong>Both settings already meet the mean budget on this fresh cohort.</strong> Equal host totals include one host gained and one lost.</p><p>Every method missed all 25 registered 500-ppm injections. Among 33 single-transit hosts, both v3 settings recover 4; TLS has 3 incidental event matches, not recovered true orbital periods. The hybrid recovers 5/99 hosts and is rejected. No new neural weights were fitted.</p><details><summary>Why exact calibration can still lose sensitivity</summary><p>Thresholds froze on 78 separate hosts using a 50% margin plus Poisson and host-bootstrap upper estimates. Exact observed-score boundaries count ties together and fix coarse-grid mechanics, but the conservative transfer rule can still select a threshold with almost no sensitivity. BLS selected ${fixed(e.thresholds.bls_exact,5)} and TLS ${fixed(e.thresholds.tls_exact,5)}. The calibration-only old-budget settings in calibration_resolution.json were not used to rescore evaluation hosts.</p><p>A single-event sideband search tests 0.5–12-hour dips without requiring repetition; the hybrid divides the control budget between that search and the neural branch. Its measured failure is evidence to retain, not a deployed improvement.</p></details>`;
      html+='</article>';
    }
    html+='<div class="callout"><h3>What these controls do and do not establish</h3><p>Rate = inverted alerts ÷ summed exposure-days × 27. It is a control-alert diagnostic, not a survey astrophysical false-positive rate. Original/injected/inverted observations test different failure modes.</p><p>The physical signals assume circular orbits, synthetic stellar density, fixed limb darkening and an empirical static PSF. Single, periodic and transit-timing-variation modes probe search behavior. These one-sector studies do not establish background-source rejection, eclipsing-binary rejection or multi-sector sensitivity. Control calibration can shift between populations.</p>'+button('#lesson/injections','Learn the matching and injection mechanisms',true)+'</div></section>';
    html+='<section id="next-experiments" class="evidence-section"><h2>Rejected ideas and the next experiments</h2><p>Behavioral v4 and diagnostic v5 did not beat their strongest declared comparators. Cross-fitted competence selection chose routing strength zero, returning the static prior. Later version numbers do not guarantee improvements.</p><div class="card"><h3>Proposed work · no measured gain yet</h3><ul><li>Test one change to cleaning or representation on a new locked weak-event cohort, with depth-stratified sensitivity at a fixed control budget.</li><li>Add background-source and eclipsing-binary injections to test host identification and contaminant rejection.</li><li>Evaluate multi-sector coverage, calibration transfer and review workload with prespecified controls.</li><li>Acquire a larger independent classifier cohort with more positive labels and matched calibration; retain availability exclusions.</li></ul><p>Keep static/variability baselines for classification and calibrated v3/TLS/BLS for event search. Do not tune on these fresh audits and continue calling them untouched.</p>'+button('#lesson/capstone','Design the next study',true)+'</div><p>The TIC 150428135 candidate case preserves its 23 September period/score and unresolved evidence. New detector benchmarks do not establish a changed candidate verdict.</p>'+button('#lesson/case','Read the dated case file',true)+'</section>';
    html+='<section id="provenance" class="evidence-section"><h2>Read the local evidence</h2><p>Tables above are a bounded snapshot compiled into the Academy. These copyable paths are relative to the repository root; open them in your editor. The Academy server does not expose the research database or parent-directory reports.</p>'+evidencePaths(P.reports)+`<details><summary>Machine-readable metric provenance</summary>${evidencePaths([['Historical adaptation',H.source],['Reused classifier',C.source],['Fresh classifier',F.source],['Physical detector',P.physical_benchmark.source],['Fresh recovery',P.fresh_recovery.source]])}</details><div class="button-row"><a class="button" href="http://127.0.0.1:8766/" target="_blank" rel="noopener noreferrer">Open live Research · port 8766 ↗</a>${button('#lesson/operations','Operating guide',true)}</div><p class="muted">Forward remote 8766 to local 8766 for the Research link. Content checked ${esc(D.checked)} · content revision ${esc(D.contentRevision)} · assessment edition ${esc(D.revision)}. Existing grades and exports remain compatible.</p></section>`;
    content.innerHTML=html;
  }
  // Optional, ungraded data outside the core course. Stage 3 supplies the cards.
  function researchLink() {return D.researchExtension?button('#research-updates','Optional: research beyond the course →',true):'';}
  function researchSourceLinks(id) {
    return (D.researchExtension?.cards||[]).filter(c=>c.sources.includes(id)||(c.related||[]).some(r=>r.sources.includes(id))).map(c=>`<a href="#research-updates/${esc(c.id)}">Tour: ${esc(c.shortTitle)}</a>`).join('');
  }
  function workflowView(id) {
    const w=D.researchExtension.workflows.find(w=>w.id===id);
    if(!w)return '';
    return `<figure class="workflow-figure"><figcaption>${esc(w.title)}</figcaption><ol class="workflow-steps">${w.steps.map(([label,text])=>`<li><strong>${esc(label)}</strong><span>${esc(text)}</span></li>`).join('')}</ol></figure><p class="notice">${esc(w.boundary)}</p>${w.project?button('#project','Inspect our deployed workflow',true):`<ul class="sources">${sourceLinks(w.sources)}</ul>`}`;
  }
  function researchPage() {
    const R=D.researchExtension;if(!R)return notFound();
    const fields=[['input','What goes in'],['mechanism','How it works'],['evidence','What was demonstrated'],['limit','Where the claim stops'],['connection','Bring it back to our work']];
    content.innerHTML=header('Optional · ungraded · about '+R.minutes+' minutes',R.title,R.lead)+`<p class="notice">This extension adds no graded questions or completion requirements. Read the tour after the capstone, or explore one example now. Your course grades stay intact.</p><nav class="research-map" aria-label="Research tour"><ol>${R.cards.map(c=>`<li><a href="#research-updates/${esc(c.id)}">${esc(c.shortTitle)}</a></li>`).join('')}</ol></nav><section class="card workflow-compare" aria-labelledby="workflow-heading"><h2 id="workflow-heading">Compare what actually happens next</h2><p>Change the workflow. Follow the ordered steps and look for the point where software requests a new observation.</p><label for="workflow-choice">Workflow to inspect</label><select id="workflow-choice" aria-controls="workflow-view">${R.workflows.map(w=>`<option value="${esc(w.id)}">${esc(w.title)}</option>`).join('')}</select><p class="muted">A teaching diagram, not a live telescope control or simulation.</p><div id="workflow-view" aria-live="polite" aria-atomic="true">${workflowView(R.workflows[0].id)}</div></section><div class="research-cards">${R.cards.map(c=>`<article class="card research-card" id="research-${esc(c.id)}" tabindex="-1" aria-labelledby="title-${esc(c.id)}"><p class="eyebrow">${esc(c.status)}</p><h2 id="title-${esc(c.id)}">${esc(c.title)}</h2><p class="research-hook">${esc(c.hook)}</p><dl class="research-evidence">${fields.map(([key,label])=>`<div class="research-${key}"><dt>${label}</dt><dd>${esc(c[key])}</dd></div>`).join('')}</dl><div class="sources"><h3>Primary sources · open in a new tab</h3><ul>${sourceLinks(c.sources)}</ul></div>${(c.related||[]).map(r=>`<details><summary>${esc(r.title)}</summary><p>${esc(r.text)}</p><ul class="sources">${sourceLinks(r.sources)}</ul></details>`).join('')}${c.reflection?`<details class="research-reflection"><summary>Pause & think: ${esc(c.reflection.question)}</summary><p>${esc(c.reflection.answer)}</p><small>Ungraded reflection · nothing is saved.</small></details>`:''}<nav class="paper-lessons" aria-label="Lessons connected to ${esc(c.shortTitle)}">${c.lessons.map(id=>`<a href="#lesson/${esc(id)}">${esc(modules.get(id).title)}</a>`).join('')}</nav><a class="research-top" href="#research-updates">Back to the tour map ↑</a></article>`).join('')}</div><section class="callout"><h2>Keep the evidence chain visible</h2><p>An alert identifies change. A candidate merits investigation. Statistical validation compares specified alternatives. New observations can support a physical classification. Automation can help at each step; it does not erase the boundaries between them.</p><p class="muted">${esc(R.sourcePolicy)}</p><div class="button-row">${button('#lesson/capstone','Back to the capstone',true)}${button('#library','Open the reading desk',true)}${button('#project','Our project evidence',true)}${button('#final','Final assessment',true)}</div></section>`;
    $('#workflow-choice').addEventListener('change',e=>{$('#workflow-view').innerHTML=workflowView(e.target.value);});
  }
  function notFound(){content.innerHTML=header('No lesson at this address','Let’s return to the course','The course was reorganized. Choose a unit or search the overview for a topic.')+button('#dashboard','Open course overview');}
  function currentRoute(){return location.hash.slice(1)||'dashboard';}
  function route() {
    activeQuiz=null;let r=currentRoute();
    const aliases={truth:'project',roadmap:'project',idea:'lesson/capstone',quiz:'practice',cards:'glossary'};r=aliases[r]||r;
    if(/^lesson\/mission-\d+$/.test(r)){const old=['light','light','impostors','contract','neurons','probability','dann','uncertainty','aliases','vetter','papers','capstone','results'];r='lesson/'+(old[Number(r.split('-').at(-1))]||'light');}
    nav(r);
    if(r==='dashboard')overview();else if(r.startsWith('unit/'))unitPage(r.split('/')[1]);else if(r.startsWith('lesson/'))lessonPage(r.split('/')[1]);
    else if(r.startsWith('check/'))quizPage('lesson/'+r.split('/')[1]);else if(r.startsWith('exam/'))quizPage(r);
    else if(r==='final'||r==='review')quizPage(r);else if(r==='mixed')quizPage('practice');else if(r==='practice')practicePage();
    else if(r==='research-updates'||r.startsWith('research-updates/'))researchPage();else if(r==='grades')gradesPage();else if(r==='library')libraryPage();else if(r==='glossary')glossaryPage();else if(r==='labs')labsPage();else if(r==='project')projectPage();else notFound();
    document.body.classList.remove('menu-open');$('#menu-toggle').setAttribute('aria-expanded','false');
    window.scrollTo(0,0);content.querySelector('h1')?.focus({preventScroll:true});
    document.title=(content.querySelector('h1')?.textContent||'Course')+' · Exoplanet Academy';
    if(r.startsWith('research-updates/')){const section=document.getElementById('research-'+r.split('/')[1]);section?.focus({preventScroll:true});section?.scrollIntoView({block:'start'});}
  }
  function download(name,text) {const url=URL.createObjectURL(new Blob([text],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  async function copy(text){try{await navigator.clipboard.writeText(text);toast('Copied.');}catch(_){toast('Clipboard unavailable. Select the displayed text and copy it manually.');}}
  function applyTheme(){document.documentElement.dataset.theme=state.theme;$('#theme-toggle').setAttribute('aria-label','Switch to '+(state.theme==='dark'?'light':'dark')+' theme');}
  content.addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.scroll){document.getElementById(b.dataset.scroll)?.scrollIntoView({behavior:'smooth',block:'start'});return;}
    if(b.dataset.labSelect){$('#chosen-lab').innerHTML=Labs.render(b.dataset.labSelect);Labs.init($('#chosen-lab'));content.querySelectorAll('[data-lab-select]').forEach(n=>n.setAttribute('aria-pressed',String(n===b)));return;}
    if(b.dataset.copy){copy(b.dataset.copy);return;}
    if(b.dataset.action==='copy-code'){copy(b.closest('.code-block').querySelector('code').textContent);return;}
    if(b.dataset.action==='retake'&&activeQuiz){quizPage(activeQuiz.scope,true);window.scrollTo(0,0);content.querySelector('h1').focus();return;}
    if(b.dataset.action==='export'){download('exoplanet-academy-progress-'+new Date().toISOString().slice(0,10)+'.json',JSON.stringify(state,null,2));return;}
    if(b.dataset.action==='legacy'&&legacy){download('exoplanet-academy-previous-edition.json',legacy);return;}
    if(b.dataset.action==='reset'&&window.confirm('Reset only the new course’s grades and drafts in this browser? Export your progress first if you want to keep it. Previous Academy notes remain untouched.')){const theme=state.theme;state=fresh();state.theme=theme;save();route();toast('Course progress reset.');}
  });
  $('#theme-toggle').addEventListener('click',()=>{state.theme=state.theme==='dark'?'light':'dark';applyTheme();save();});
  $('#menu-toggle').addEventListener('click',()=>{const open=document.body.classList.toggle('menu-open');$('#menu-toggle').setAttribute('aria-expanded',String(open));});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(document.body.classList.contains('menu-open')&&$('.sidebar').contains(document.activeElement))$('#menu-toggle').focus();document.body.classList.remove('menu-open');$('#menu-toggle').setAttribute('aria-expanded','false');}});
  window.addEventListener('hashchange',()=>{if(currentRoute()==='main-content'){$('#main-content').focus();return;}route();});
  $('#save-status').textContent=storageOK?'Progress stays in this browser':'Not saved · export progress';applyTheme();route();
})();
