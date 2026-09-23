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
    html+='</div><section class="callout"><h2>Your project is the running case study</h2><p>The watcher monitors two configured TESS controls. The DANN comparison is finished, but DANN did not earn replacement of the reference CNN. Learn why those facts matter for discovery claims.</p>'+button('#project','Explore the project map',true)+'</section>';
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
  function sourceLinks(ids) {
    return ids.map(id=>D.sources.find(s=>s.id===id)).filter(Boolean).map(s=>`<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)} ↗</a><small>${esc(s.year)} · ${esc(s.status)}</small></li>`).join('');
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
    html+='<div class="lesson-footer">'+(previous?button('#lesson/'+previous.id,'← Previous lesson',true):button('#dashboard','← Course overview',true))+(next?button('#lesson/'+next.id,'Next lesson →'):button('#final','Take the final assessment →'))+'</div></div>';
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
    $('#quiz-next').innerHTML=`<div class="button-row"><button class="button secondary" data-action="retake">Try a fresh attempt</button>${button('#review','Review mistakes',true)}${next}${button('#grades','View gradebook',true)}</div>`;
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
    content.innerHTML=header('Primary sources · checked '+D.checked,'The research reading desk','Read by task and evidence, not by headline accuracy. Start with the course explanations, then use these sources to deepen and challenge them.')+`<p class="notice">This is a curated reading path, not an exhaustive “best model” leaderboard. 2026 preprints are marked explicitly; their reported results have not been independently reproduced here. ${button('#lesson/frontier','Read the guided comparison',true)}</p><div class="library-grid">${D.sources.map(s=>`<article class="paper-card"><p class="eyebrow">${esc(s.year)} · ${esc(s.status)}</p><h2><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)} ↗</a></h2><p>${esc(s.takeaway)}</p><div class="paper-lessons">${D.modules.filter(m=>m.sources.includes(s.id)).slice(0,3).map(m=>`<a href="#lesson/${m.id}">${esc(m.title)}</a>`).join('')}</div></article>`).join('')}</div>`;
  }
  function glossaryPage() {
    content.innerHTML=header('Definitions with a route back to understanding','Your working vocabulary','Each term links to a lesson that explains the mechanism and tests your understanding.')+'<label class="search-label glossary-search">Find a term<input id="glossary-search" type="search" placeholder="Gradient, DANN, ephemeris…"></label><p id="glossary-count" role="status" class="muted"></p><dl class="glossary">'+D.glossary.slice().sort((a,b)=>a.term.localeCompare(b.term)).map(g=>`<div data-term="${esc((g.term+' '+g.meaning).toLowerCase())}"><dt>${esc(g.term)}</dt><dd>${esc(g.meaning)} <a href="#lesson/${g.lesson}">Learn it →</a></dd></div>`).join('')+'</dl>';
    $('#glossary-search').addEventListener('input',e=>{const term=e.target.value.toLowerCase();let n=0;content.querySelectorAll('[data-term]').forEach(el=>{el.hidden=!el.dataset.term.includes(term);if(!el.hidden)n++;});$('#glossary-count').textContent=`${n} matching terms`;});
  }
  function labsPage() {
    content.innerHTML=header('See the mechanism change','Interactive lab','Nine small experiments run locally. They teach a formula or mechanism; they do not train a research model or evaluate real telescope data.')+'<div class="lab-index">'+Object.entries(Labs.names).map(([id,name])=>`<button class="chip" data-lab-select="${id}">${esc(name)}</button>`).join('')+'</div><div id="chosen-lab">'+Labs.render('gradient')+'</div>';
    Labs.init(content);
  }
  function projectPage() {
    const P=D.project;
    let html=header('Repository snapshot · '+P.updated,'The project, end to end','Follow one signal from public data to a saved review. These are dated teaching facts; the Research website contains the live records.');
    html+='<div class="project-stages">'+P.stages.map((s,i)=>`<a href="#lesson/${s[2]}" class="stage"><span>${i+1}</span><div><h2>${esc(s[0])}</h2><p>${esc(s[1])}</p></div><b aria-hidden="true">↗</b></a>`).join('')+'</div>';
    html+='<section class="card"><p class="eyebrow">Completed experiment · pilot-v1</p><h2>DANN is implemented. Its benefit was not demonstrated.</h2><div class="table-wrap"><table><caption>TESS audit AP · 82 rows / 79 groups · three seeds per approach</caption><thead><tr><th>Approach</th><th>Mean AP</th><th>Seed SD</th></tr></thead><tbody>'+P.metrics.map(r=>'<tr>'+r.map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div><p>All 15 short-budget fits completed. Most selected checkpoints are at the update limit; convergence is not established. The audit came from the prior validation pool. These are not candidate probabilities or directly comparable to the separate 335-row benchmark.</p><p>The reference CNN remains primary. Comparison scores were appended to 44 retained proposals: 17 real controls and 27 synthetic/transformed controls. This is not a count of new planets.</p>'+button('#lesson/results','Learn to interpret these results',true)+'</section>';
    html+='<section class="callout"><h2>What is still missing?</h2><p>A larger locked blind-search evaluation, realistic completeness and false-alarm estimates, complete source-location vetting for the highlighted signal, and applicable astrophysical validation. The approximately 25.3244-day unmatched signal has no established planet probability.</p>'+button('#lesson/case','Work through the candidate case',true)+'</section>';
    html+='<h2>Useful commands</h2><p>Run shell commands from the project root. Inspect status before starting another server. Live watcher updates do not automatically create snapshots or push to Git.</p>'+codeBlock('# From your Thesis-Rojin checkout\n.venv/bin/python -m scripts.research status\n.venv/bin/python -m scripts.research watch-status\n# Check the configured targets for new public products now:\n.venv/bin/python -m scripts.research watch-auto-check')+codeBlock('# Run only if the relevant service is not already listening.\n# From your Thesis-Rojin checkout\n# Academy, port 8765:\n.venv/bin/python academy/serve.py --host 127.0.0.1 --port 8765\n# Research, in another terminal, port 8766:\n.venv/bin/python -m scripts.research serve --host 127.0.0.1 --port 8766');
    html+='<h2>Read the local evidence</h2><p class="muted">Paths are relative to the repository root. Copy a path and open it in VS Code; the Academy does not expose the whole repository through its web server.</p><ul class="evidence-list">'+P.evidence.map(([label,path])=>`<li><div><strong>${esc(label)}</strong><code>${esc(path)}</code></div><button class="text-button" data-copy="${esc(path)}">Copy path</button></li>`).join('')+'</ul><div class="button-row"><a class="button" href="http://127.0.0.1:8766/" target="_blank" rel="noopener noreferrer">Open Research · port 8766 ↗</a>'+button('#lesson/operations','Read the operating guide',true)+'</div><p class="muted">The Research link requires port 8766 to be forwarded to this computer. Research requires remote 8766 → local 8766. If VS Code assigns a different local port, remove the conflicting forward and choose Change Local Port → 8766.</p>';
    content.innerHTML=html;
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
    else if(r==='grades')gradesPage();else if(r==='library')libraryPage();else if(r==='glossary')glossaryPage();else if(r==='labs')labsPage();else if(r==='project')projectPage();else notFound();
    document.body.classList.remove('menu-open');$('#menu-toggle').setAttribute('aria-expanded','false');
    window.scrollTo(0,0);content.querySelector('h1')?.focus({preventScroll:true});
    document.title=(content.querySelector('h1')?.textContent||'Course')+' · Exoplanet Academy';
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
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){document.body.classList.remove('menu-open');$('#menu-toggle').setAttribute('aria-expanded','false');}});
  window.addEventListener('hashchange',()=>{if(currentRoute()==='main-content'){$('#main-content').focus();return;}route();});
  $('#save-status').textContent=storageOK?'Progress stays in this browser':'Not saved · export progress';applyTheme();route();
})();
