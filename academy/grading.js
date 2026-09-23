/* Pure, local assessment functions; also executable in Node for verification. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.AcademyGrade = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function numeric(value) {
    if (typeof value !== 'string' && typeof value !== 'number') return null;
    const text = String(value).trim();
    if (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(text)) return null;
    const n = Number(text);
    return Number.isFinite(n) ? n : null;
  }
  function answered(q, answer) {
    if (q.type === 'number') return numeric(answer) !== null;
    if (q.type === 'single') return Number.isInteger(answer) && answer >= 0 && answer < q.options.length;
    return q.type === 'multi' && Array.isArray(answer) && answer.length > 0 &&
      new Set(answer).size === answer.length && answer.every(v => Number.isInteger(v) && v >= 0 && v < q.options.length);
  }
  function correct(q, answer) {
    if (!answered(q, answer)) return false;
    if (q.type === 'number') return Math.abs(numeric(answer) - q.answer) <= q.tolerance + 1e-10;
    if (q.type === 'single') return answer === q.answer;
    return answer.length === q.answer.length && q.answer.every(v => answer.includes(v));
  }
  function grade(questions, answers, threshold = .8) {
    const missing = questions.filter(q => !answered(q, answers[q.id])).map(q => q.id);
    if (missing.length) return {complete:false, missing};
    const results = questions.map(q => ({id:q.id, correct:correct(q, answers[q.id])}));
    const score = results.filter(r => r.correct).length;
    const total = results.length;
    const needed = Math.ceil(total * threshold);
    const percent = total ? 100 * score / total : 0;
    return {complete:true, results, score, total, needed, percent, passed:total > 0 && score >= needed,
      letter:percent >= 90 ? 'A' : percent >= 80 ? 'B' : percent >= 70 ? 'C' : percent >= 60 ? 'D' : 'F'};
  }
  function answerText(q) {
    if (q.type === 'number') return `${q.answer} ${q.unit} (±${q.tolerance})`;
    if (q.type === 'multi') return q.answer.map(i => q.options[i]).join(' + ');
    return q.options[q.answer];
  }
  // A teaching PRNG, deliberately separate from Python/NumPy/PyTorch generators.
  function rng(seed) {
    let a = Number(seed) >>> 0;
    return function () {
      a += 0x6D2B79F5;
      let t = a;
      t = Math.imul(t ^ t >>> 15, t | 1);
      t ^= t + Math.imul(t ^ t >>> 7, t | 61);
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function shuffle(items, random = Math.random) {
    const a = items.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }
  function softmax(scores) {
    const max = Math.max(...scores), weights = scores.map(v => Math.exp(v - max));
    const sum = weights.reduce((a,b) => a+b, 0);
    return weights.map(v => v/sum);
  }
  function trainToy(weight, rate, steps) {
    const rows = [];
    for (let i=0; i<=steps; i++) {
      const prediction = 2*weight, loss = .5*(prediction-4)**2;
      rows.push({step:i,weight,prediction,loss,gradient:(prediction-4)*2});
      weight -= rate*(prediction-4)*2;
    }
    return rows;
  }
  return {numeric,answered,correct,grade,answerText,rng,shuffle,softmax,trainToy};
});
