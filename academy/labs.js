(function () {
  'use strict';
  const G = window.AcademyGrade;
  const names = {transit:'Change the planet, star and dilution',fold:'Try the wrong orbital period',
    'base-rate':'Watch false alerts overwhelm true ones',trials:'Give noise more chances',
    gradient:'Train a tiny model yourself',seed:'Same seed, same starting stream',
    convolution:'Slide a filter across a dip',attention:'Change a query, change the mixture',dann:'See the reversed gradient'};
  const controls = {
    transit:[['planet','Planet radius · Earth radii',2,.5,15,.1],['star','Star radius · solar radii',1,.2,2,.1],['dilution','Unrelated fraction of total light · %',0,0,90,5]],
    fold:[['period','Trial period · days',5,2.5,10,.5]],
    'base-rate':[['prevalence','True positives in population · %',.1,.01,10,.01],['sensitivity','Sensitivity · %',95,0,100,1],['fpr','False-positive rate · %',1,.01,10,.01]],
    trials:[['stars','Number of stars',100000,1000,1000000,1000],['trials','Independent trials per star · hypothetical',100,1,1000,1],['p','Null exceedance probability per trial',.000001,.0000001,.00001,.0000001]],
    gradient:[['weight','Initial weight',1,-2,3,.1],['rate','Learning rate',.1,.01,.6,.01],['steps','Updates',5,1,20,1]],
    seed:[['seed','Teaching generator seed',42,1,100,1],['steps','Updates with learning rate 0.1',3,0,12,1]],
    convolution:[['position','Window start index',0,0,5,1]],
    attention:[['query','Scalar query q',1,-3,3,.1]],
    dann:[['task','Task gradient',2,-4,4,.5],['domain','Domain gradient',3,-4,4,.5],['lambda','Adversary strength λ',.5,0,2,.1]]
  };
  function fmt(x) { return Math.abs(x)>=10000 || (x!==0 && Math.abs(x)<.0001) ? x.toExponential(3) : Number(x.toFixed(5)).toLocaleString('en',{maximumFractionDigits:5}); }
  function plot(series, xLabel, yLabel, dots=false) {
    const all=series.flat(), xs=all.map(p=>p[0]), ys=all.map(p=>p[1]);
    let xmin=Math.min(...xs), xmax=Math.max(...xs), ymin=Math.min(...ys), ymax=Math.max(...ys);
    if(xmin===xmax) xmax=xmin+1;
    if(ymin===ymax) ymax=ymin+1;
    const pad=(ymax-ymin)*.1;
    ymin=ymin>=0?Math.max(0,ymin-pad):ymin-pad;
    ymax+=pad;
    const x=v=>65+480*(v-xmin)/(xmax-xmin), y=v=>220-180*(v-ymin)/(ymax-ymin);
    let html=`<svg viewBox="0 0 600 280" role="img" aria-label="${yLabel} versus ${xLabel}. Numerical values and interpretation appear below."><path class="axis" d="M65 25V220H555"/><text x="305" y="272" text-anchor="middle">${xLabel}</text><text x="65" y="16">${yLabel}</text><text x="58" y="45" text-anchor="end">${fmt(ymax)}</text><text x="58" y="220" text-anchor="end">${fmt(ymin)}</text><text x="65" y="241">${fmt(xmin)}</text><text x="545" y="241" text-anchor="end">${fmt(xmax)}</text>`;
    series.forEach((s,i)=>{
      if(!dots) html+=`<polyline class="plot-line line-${i}" points="${s.map(p=>`${x(p[0])},${y(p[1])}`).join(' ')}"/>`;
      s.forEach(p=>{if(dots||s.length<22)html+=`<circle class="plot-dot line-${i}" cx="${x(p[0])}" cy="${y(p[1])}" r="3.5"/>`;});
    });
    return html+'</svg>';
  }
  function metrics(rows) { return '<dl class="lab-metrics">'+rows.map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')+'</dl>'; }
  function render(type) {
    if(!names[type]) return '';
    return `<section class="lab" data-lab="${type}"><p class="eyebrow">Interactive experiment · runs in your browser</p><h2>${names[type]}</h2><p class="muted">Move a control, predict the change, then inspect the result. This is a teaching simulation, not an analysis of telescope data.</p><div class="lab-controls">${controls[type].map(([id,label,v,min,max,step])=>`<label for="lab-${id}">${label}<output id="out-${id}" for="lab-${id}">${v}</output><input id="lab-${id}" name="${id}" type="range" min="${min}" max="${max}" step="${step}" value="${v}"></label>`).join('')}</div><div class="lab-result" aria-live="polite"></div></section>`;
  }
  function update(el) {
    const p={}; el.querySelectorAll('input').forEach(n=>{p[n.name]=Number(n.value);el.querySelector('#out-'+n.name).textContent=fmt(p[n.name]);});
    const t=el.dataset.lab; let html='';
    if(t==='transit') {
      const depth=(p.planet/(109*p.star))**2, obs=depth*(1-p.dilution/100);
      const curve=Array.from({length:61},(_,i)=>{const x=-3+i/10;const shape=Math.abs(x)<=.8?1:Math.abs(x)<1? (1-Math.abs(x))/.2:0;return[x,1-obs*shape];});
      html=plot([curve],'Hours from transit center','Relative flux')+metrics([['Undiluted depth',fmt(depth*1e6)+' ppm'],['Observed depth',fmt(obs*1e6)+' ppm'],['Radius inferred if dilution ignored',fmt(p.planet*Math.sqrt(1-p.dilution/100))+' Earth radii']])+ '<p>The amplitude uses δ=(Rp/R★)². The drawn trapezoid fixes duration for illustration; it is not a limb-darkened physical fit. Contamination here is constant light from other sources, and the target is assumed to host the event.</p>';
    } else if(t==='fold') {
      const times=[2,7,12,17,22], phases=times.map(v=>((v-2)/p.period)%1);
      html=plot([phases.map((v,i)=>[v,i+1])],'Phase in [0, 1)','Event number',true)+metrics([['Observed event days',times.join(', ')],['Folded phases',phases.map(fmt).join(', ')],['Trial period',fmt(p.period)+' days']])+ '<p>At 5 days these events align. At 2.5 days they also align, but that trial predicts additional events between them. Alignment alone cannot resolve an alias: inspect whether those extra times have usable observations and measured dips.</p>';
    } else if(t==='base-rate') {
      const population=100000, pos=population*p.prevalence/100, tp=pos*p.sensitivity/100, fp=(population-pos)*p.fpr/100, precision=tp/(tp+fp);
      html=metrics([['True alerts out of 100,000',fmt(tp)],['False alerts out of 100,000',fmt(fp)],['Alert precision',fmt(100*precision)+'%']])+`<div class="mix-bar" role="img" aria-label="True alerts ${fmt(precision*100)} percent; false alerts ${fmt((1-precision)*100)} percent"><span style="width:${precision*100}%"></span></div><p>The mint fraction represents true alerts; the remainder represents false alerts. Counts are expected values and may be fractional. Precision = true alerts / all alerts. Lower prevalence can overwhelm a model with false positives even when its sensitivity is unchanged.</p>`;
    } else if(t==='trials') {
      const n=p.stars*p.trials, expected=n*p.p, any=-Math.expm1(n*Math.log1p(-p.p));
      html=metrics([['Hypothetical independent trials',fmt(n)],['Expected null exceedances',fmt(expected)],['Probability of ≥1 exceedance',fmt(any*100)+'%']])+ '<p>Expected count = Np; probability of at least one = 1−(1−p)ᴺ under independent null trials. Real search templates overlap and noise is correlated. This toy count is not a survey false-alarm estimate.</p>';
    } else if(t==='gradient') {
      const rows=G.trainToy(p.weight,p.rate,p.steps), last=rows.at(-1);
      html=plot([rows.map(r=>[r.step,r.loss])],'Optimizer updates','Squared loss')+metrics([['Final weight',fmt(last.weight)],['Prediction for x=2',fmt(last.prediction)],['Target',4],['Final loss',fmt(last.loss)]])+ '<p>One example: x=2, target=4; prediction=2w; loss=½(2w−4)². Gradient=(2w−4)×2. Update w←w−η×gradient. Try a learning rate above 0.5 to see this toy problem diverge rather than learn.</p><div class="table-wrap"><table><caption>Last training steps</caption><thead><tr><th>Step</th><th>Weight</th><th>Loss</th><th>Gradient</th></tr></thead><tbody>'+rows.slice(-6).map(r=>`<tr><td>${r.step}</td><td>${fmt(r.weight)}</td><td>${fmt(r.loss)}</td><td>${fmt(r.gradient)}</td></tr>`).join('')+'</tbody></table></div>';
    } else if(t==='seed') {
      const seeds=[p.seed,p.seed,p.seed+1], streams=seeds.map(s=>{const rng=G.rng(s);return[rng(),rng(),rng()];});
      const runs=streams.map(s=>G.trainToy(2*s[0]-1,.1,p.steps));
      html=plot(runs.map(r=>r.map(v=>[v.step,v.loss])),'Optimizer updates','Squared loss')+metrics(streams.map((r,i)=>['Run '+(i+1)+' · seed '+seeds[i],r.map(v=>v.toFixed(5)).join(', ')]))+ '<p>Runs 1 and 2 use the same seed and overlap exactly. Run 3 starts a different stream. Only initialization is random in this toy, so all three approach the same optimum with enough updates. Real networks also randomize batch order, dropout and other operations. This JavaScript generator is not Python, NumPy or PyTorch’s generator.</p>';
    } else if(t==='convolution') {
      const input=[1,1,1,.9,.9,1,1,1], kernel=[1,-2,1];const values=Array.from({length:6},(_,i)=>input.slice(i,i+3).reduce((s,v,j)=>s+v*kernel[j],0));
      html='<div class="number-strip">'+input.map((v,i)=>`<span class="${i>=p.position&&i<p.position+3?'selected':''}"><small>bin ${i}</small>${v}</span>`).join('')+'</div>'+plot([values.map((v,i)=>[i,v])],'Window start index','Filter response')+metrics([['Selected window',input.slice(p.position,p.position+3).join(', ')],['Kernel','1, −2, 1'],['Selected response',fmt(values[p.position])]])+'<p>Multiply each selected value by the corresponding kernel weight and add. This is the cross-correlation operation commonly called convolution in ML libraries. The same kernel slides across the curve. Real filters are learned; this one is hand-chosen to make the arithmetic visible.</p>';
    } else if(t==='attention') {
      const keys=[-1,0,1],values=[2,4,10],weights=G.softmax(keys.map(k=>p.query*k)),value=weights.reduce((s,w,i)=>s+w*values[i],0);
      html='<div class="attention-flow">'+weights.map((w,i)=>`<div><span>Token ${i+1}</span><strong>${(100*w).toFixed(1)}%</strong><div class="weight-bar"><span style="width:${w*100}%"></span></div><small>key ${keys[i]} · value ${values[i]}</small></div>`).join('')+'</div>'+metrics([['Weights sum',fmt(weights.reduce((a,b)=>a+b,0))],['Weighted output',fmt(value)]])+'<p>Scalar teaching example: scores = query × keys; weights = softmax(scores); output = Σ(weight × value). At query zero all tokens have equal weight. Real attention learns vector projections and uses dimensional scaling and masks. Token weights are not planet probabilities.</p>';
    } else if(t==='dann') {
      const reversed=-p.lambda*p.domain,g=p.task+reversed;
      html='<div class="pipeline small"><span>Task gradient<br><strong>'+fmt(p.task)+'</strong></span><b>+</b><span>Reversed domain gradient<br><strong>'+fmt(reversed)+'</strong></span><b>→</b><span>Feature gradient<br><strong>'+fmt(g)+'</strong></span></div>'+metrics([['Domain gradient before reversal',fmt(p.domain)],['Feature update from θ=1, η=0.1',fmt(1-.1*g)]])+'<p>The feature extractor receives gtask − λgdomain. The domain head’s own optimizer still minimizes domain-classification loss. Set λ=0 to remove the adversarial feature contribution; increase it to see a possible conflict with the task direction. This illustrates a gradient step, not whether alignment benefits real TESS data.</p>';
    }
    el.querySelector('.lab-result').innerHTML=html;
  }
  function init(container) { container.querySelectorAll('[data-lab]').forEach(el=>{update(el);el.addEventListener('input',()=>update(el));}); }
  window.AcademyLabs={render,init,names};
})();
