'use strict';
const COURSE_KEY = 'pdffc_progress_v1';
const MODULES = [
  {id:'mod00',pages:['index','lab']},
  {id:'mod01',pages:['index','lesson_structure','lab','quiz']},
  {id:'mod02',pages:['index','lesson_metadata','lab','quiz']},
  {id:'mod03',pages:['index','lesson_incremental','lab','quiz']},
  {id:'mod04',pages:['index','lesson_images','lab','quiz']},
  {id:'mod05',pages:['index','lesson_overlay','lab','quiz']},
  {id:'mod06',pages:['index','lesson_exif','lab','quiz']},
  {id:'mod07',pages:['index','lab','quiz']},
  {id:'final',pages:['assessment']},
];

// Hours assigned per module, used for the certificate. Matches the course's own
// published duration estimates (index.html / module overview pages).
const MODULE_HOURS = {
  mod00: 20/60, mod01: 60/60, mod02: 50/60, mod03: 50/60,
  mod04: 75/60, mod05: 70/60, mod06: 55/60, mod07: 90/60,
};
const TOTAL_COURSE_HOURS = Object.values(MODULE_HOURS).reduce((a,b)=>a+b, 0);

// Order in which modules must be passed for sequential (soft-lock) progression.
// "final" requires every module 00-07 to be passed first.
const MODULE_ORDER = ['mod00','mod01','mod02','mod03','mod04','mod05','mod06','mod07','final'];

const Progress = {
  data: null,
  load() {
    try { this.data = JSON.parse(localStorage.getItem(COURSE_KEY)) || this._blank(); }
    catch(_) { this.data = this._blank(); }
    return this;
  },
  _blank() {
    const d = {completed:{}, quizScores:{}, startedAt:null};
    MODULES.forEach(m => { d.completed[m.id] = {}; });
    return d;
  },
  save() { try { localStorage.setItem(COURSE_KEY, JSON.stringify(this.data)); } catch(_){} return this; },
  markPage(modId, pageId) {
    if (!this.data.completed[modId]) this.data.completed[modId] = {};
    this.data.completed[modId][pageId] = true;
    if (!this.data.startedAt) this.data.startedAt = Date.now();
    this.save(); this.updateUI();
  },
  isPageDone(modId, pageId) { return !!(this.data.completed[modId] && this.data.completed[modId][pageId]); },
  isModuleDone(modId) {
    const mod = MODULES.find(m => m.id === modId);
    if (!mod) return false;
    // Non-quiz pages (index, lesson, lab) still use scroll/click completion.
    // A 'quiz' or 'assessment' page additionally requires a passing score --
    // visiting it is not enough.
    return mod.pages.every(p => {
      if (p === 'quiz' || p === 'assessment') {
        const score = this.data.quizScores[modId];
        return !!score && score.pct >= 70;
      }
      return this.isPageDone(modId, p);
    });
  },
  isModuleLocked(modId) {
    // A module is locked (soft) if any module earlier in MODULE_ORDER is not yet passed.
    const idx = MODULE_ORDER.indexOf(modId);
    if (idx <= 0) return false;
    for (let i = 0; i < idx; i++) {
      if (!this.isModuleDone(MODULE_ORDER[i])) return true;
    }
    return false;
  },
  isCourseComplete() {
    return MODULE_ORDER.every(id => this.isModuleDone(id));
  },
  overallPct() {
    let total = 0, done = 0;
    MODULES.forEach(m => { m.pages.forEach(p => { total++; if (this.isPageDone(m.id, p)) done++; }); });
    return total ? Math.round((done/total)*100) : 0;
  },
  saveQuizScore(modId, score, total) {
    this.data.quizScores[modId] = {score, total, pct:Math.round(score/total*100)};
    this.save();
  },
  reset() { this.data = this._blank(); this.save(); this.updateUI(); },
  updateUI() {
    const pct = this.overallPct();
    document.querySelectorAll('.overall-progress-fill').forEach(el => el.style.width = pct + '%');
    document.querySelectorAll('.progress-pct').forEach(el => el.textContent = pct + '%');
    document.querySelectorAll('.progress-badge').forEach(el => el.textContent = pct + '%');
    MODULES.forEach(m => {
      const el = document.querySelector(`.sidebar-item[data-mod="${m.id}"]`);
      if (!el) return;
      if (this.isModuleDone(m.id)) {
        el.classList.add('completed');
        el.classList.remove('locked');
        const n = el.querySelector('.sidebar-num'); if (n) n.textContent = '✓';
        const lockIcon = el.querySelector('.sidebar-lock'); if (lockIcon) lockIcon.remove();
      } else if (this.isModuleLocked(m.id)) {
        el.classList.add('locked');
        if (!el.querySelector('.sidebar-lock')) {
          const lock = document.createElement('span');
          lock.className = 'sidebar-lock';
          lock.textContent = '🔒';
          lock.title = 'Complete earlier modules first (you can still proceed if you choose)';
          el.querySelector('.sidebar-check')?.replaceWith(lock);
        }
      }
    });
    // Soft-lock banner: show on any page whose module is locked, reminding the
    // student they're ahead of the recommended sequence. Does not block access.
    const bMod = document.body.dataset.mod;
    if (bMod && this.isModuleLocked(bMod)) {
      this._showSkipAheadBanner(bMod);
    }
    // Certificate eligibility banner on the home page
    if (this.isCourseComplete()) {
      document.querySelectorAll('.cert-ready-banner').forEach(el => el.classList.remove('hidden'));
    }
  },
  _showSkipAheadBanner(modId) {
    if (document.querySelector('.skip-ahead-banner')) return; // already shown
    const idx = MODULE_ORDER.indexOf(modId);
    const prevId = idx > 0 ? MODULE_ORDER[idx - 1] : null;
    const banner = document.createElement('div');
    banner.className = 'skip-ahead-banner';
    banner.innerHTML = '⚠️ You have not yet passed an earlier module' +
      (prevId ? ` (<strong>${prevId.replace('mod','Module ')}</strong> or before)` : '') +
      '. You are welcome to continue, but content here may assume knowledge from earlier modules.';
    const header = document.querySelector('.page-header');
    if (header && header.parentElement) header.parentElement.insertBefore(banner, header);
  }
};

const Quiz = {
  container: null, questions: [], current: 0, answers: {}, modId: null,
  init(el, modId) {
    this.container = el; this.modId = modId;
    this.questions = Array.from(el.querySelectorAll('.question-block'));
    this.current = 0; this.answers = {};
    if (!this.questions.length) return;
    el.querySelectorAll('.option-radio').forEach(opt => opt.addEventListener('click', () => this.selectOption(opt)));
    el.querySelector('.btn-submit')?.addEventListener('click', () => this.submitAnswer());
    el.querySelector('.btn-next')?.addEventListener('click', () => this.nextQuestion());
    el.querySelector('.btn-prev')?.addEventListener('click', () => this.prevQuestion());
    el.querySelector('.btn-retry')?.addEventListener('click', () => this.retry());
    this.restoreProgress();
  },
  _storageKey() { return 'pdffc_quiz_inprogress_' + this.modId; },
  saveProgress() {
    try {
      sessionStorage.setItem(this._storageKey(), JSON.stringify({ current: this.current, answers: this.answers }));
    } catch(_) {}
  },
  clearProgress() {
    try { sessionStorage.removeItem(this._storageKey()); } catch(_) {}
  },
  restoreProgress() {
    let saved = null;
    try { saved = JSON.parse(sessionStorage.getItem(this._storageKey())); } catch(_) {}
    if (!saved || typeof saved !== 'object') { this.showQuestion(0); return; }

    // Replay each previously-answered question's visual state (selection,
    // correct/incorrect highlighting, feedback box) before showing the page.
    this.answers = saved.answers || {};
    Object.entries(this.answers).forEach(([idxStr, ans]) => {
      const qBlock = this.questions[parseInt(idxStr, 10)];
      if (!qBlock || !ans) return;
      qBlock.dataset.answered = 'true';
      qBlock.querySelectorAll('.option-radio').forEach(o => {
        if (o.dataset.value === ans.given) o.classList.add('selected');
        if (o.dataset.value === ans.correct) o.classList.add('correct');
        else if (o.dataset.value === ans.given && !ans.isRight) o.classList.add('incorrect');
      });
      const fb = qBlock.querySelector('.feedback-box');
      if (fb) fb.classList.add('show', ans.isRight ? 'feedback-correct' : 'feedback-incorrect');
    });

    const restoreIdx = Math.min(saved.current || 0, this.questions.length - 1);
    this.showQuestion(Math.max(0, restoreIdx));
  },
  showQuestion(idx) {
    this.questions.forEach((q,i) => q.classList.toggle('active', i===idx));
    this.current = idx; this.updateProgressBar(); this.updateNavButtons();
    this.syncControlsToCurrentQuestion();
    this.saveProgress();
  },
  syncControlsToCurrentQuestion() {
    // Whenever the visible question changes (Previous, Next, or initial load),
    // the Submit/Next buttons must reflect THIS question's answered state --
    // not whatever state they were left in by the question shown previously.
    const qBlock = this.questions[this.current];
    const sub = this.container.querySelector('.btn-submit');
    const nxt = this.container.querySelector('.btn-next');
    const hint = this.container.querySelector('.quiz-controls > span');
    if (!qBlock) return;
    if (qBlock.dataset.answered === 'true') {
      // Already answered: hide Submit, show Next (re-labelled if this is the last question)
      if (sub) sub.classList.add('hidden');
      if (nxt) {
        nxt.classList.remove('hidden');
        if (this.current === this.questions.length - 1) { nxt.textContent = '📊 View Results'; nxt.dataset.final = 'true'; }
        else { nxt.textContent = 'Next →'; delete nxt.dataset.final; }
      }
      if (hint) hint.textContent = '';
    } else {
      // Not yet answered: show Submit (disabled until an option is picked), hide Next
      const hasSelection = !!qBlock.querySelector('.option-radio.selected');
      if (sub) { sub.classList.remove('hidden'); sub.disabled = !hasSelection; }
      if (nxt) { nxt.classList.add('hidden'); delete nxt.dataset.final; }
      if (hint) hint.textContent = 'Select an answer to continue';
    }
  },
  selectOption(optEl) {
    const qBlock = optEl.closest('.question-block');
    if (qBlock.dataset.answered) return;
    qBlock.querySelectorAll('.option-radio').forEach(o => o.classList.remove('selected'));
    optEl.classList.add('selected');
    const btn = this.container.querySelector('.btn-submit');
    if (btn) btn.disabled = false;
  },
  submitAnswer() {
    const qBlock = this.questions[this.current];
    if (qBlock.dataset.answered) return;
    const selected = qBlock.querySelector('.option-radio.selected');
    if (!selected) return;
    const correct = qBlock.dataset.correct, given = selected.dataset.value;
    const isRight = given === correct;
    this.answers[this.current] = {given, correct, isRight};
    qBlock.dataset.answered = 'true';
    this.saveProgress();
    qBlock.querySelectorAll('.option-radio').forEach(o => {
      if (o.dataset.value === correct) o.classList.add('correct');
      else if (o.dataset.value === given && !isRight) o.classList.add('incorrect');
    });
    const fb = qBlock.querySelector('.feedback-box');
    if (fb) { fb.classList.add('show', isRight ? 'feedback-correct' : 'feedback-incorrect'); }
    const sub = this.container.querySelector('.btn-submit');
    const nxt = this.container.querySelector('.btn-next');
    if (sub) sub.classList.add('hidden');
    if (nxt) {
      nxt.classList.remove('hidden');
      if (this.current === this.questions.length - 1) { nxt.textContent = '📊 View Results'; nxt.dataset.final = 'true'; }
    }
  },
  nextQuestion() {
    const nxt = this.container.querySelector('.btn-next');
    if (nxt?.dataset.final) { this.showResults(); return; }
    if (this.current < this.questions.length - 1) {
      this.showQuestion(this.current + 1);
    }
  },
  prevQuestion() { if (this.current > 0) this.showQuestion(this.current - 1); },
  showResults() {
    const correct = Object.values(this.answers).filter(a => a.isRight).length;
    const total = this.questions.length, pct = Math.round(correct/total*100), pass = pct >= 70;
    this.questions.forEach(q => q.classList.remove('active'));
    this.clearProgress();
    const res = this.container.querySelector('.quiz-results');
    if (res) {
      res.classList.add('show');
      const c = res.querySelector('.score-circle');
      if (c) { c.textContent = pct + '%'; c.classList.add(pass ? 'score-pass' : 'score-fail'); }
      const msg = res.querySelector('.score-msg');
      if (msg) msg.textContent = pass ? `Well done — ${correct} of ${total} correct. Module complete.` : `${correct} of ${total} correct. Review the material and try again.`;
    }
    Progress.saveQuizScore(this.modId, correct, total);
    if (pass) Progress.markPage(this.modId, 'quiz');
    const ctrl = this.container.querySelector('.quiz-controls');
    if (ctrl) ctrl.classList.add('hidden');
  },
  retry() {
    this.current = 0; this.answers = {};
    this.clearProgress();
    this.questions.forEach(q => {
      delete q.dataset.answered; q.classList.remove('active');
      q.querySelectorAll('.option-radio').forEach(o => o.classList.remove('selected','correct','incorrect'));
      const fb = q.querySelector('.feedback-box');
      if (fb) fb.classList.remove('show','feedback-correct','feedback-incorrect');
    });
    const res = this.container.querySelector('.quiz-results'); if (res) res.classList.remove('show');
    const ctrl = this.container.querySelector('.quiz-controls'); if (ctrl) ctrl.classList.remove('hidden');
    this.showQuestion(0);
  },
  updateProgressBar() {
    const fill = this.container.querySelector('.quiz-progress-fill');
    if (fill) fill.style.width = (this.questions.length ? Math.round(((this.current+1)/this.questions.length)*100) : 0) + '%';
  },
  updateNavButtons() {
    const prev = this.container.querySelector('.btn-prev'); if (prev) prev.disabled = this.current === 0;
  }
};

function initTabs() {
  document.querySelectorAll('.tool-tabs').forEach(tabBar => {
    // Get sibling panels — only the .tool-panel elements immediately following this tabBar
    const panels = [];
    let sib = tabBar.nextElementSibling;
    while (sib && sib.classList.contains('tool-panel')) {
      panels.push(sib);
      sib = sib.nextElementSibling;
    }
    const groupId = tabBar.dataset.tabgroup || 'global';

    tabBar.querySelectorAll('.tool-tab').forEach((tab, idx) => {
      tab.addEventListener('click', () => {
        tabBar.querySelectorAll('.tool-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        panels.forEach((p, i) => p.classList.toggle('active', i === idx));
        // Persist per group so each exercise remembers independently,
        // but also update the global platform preference
        try {
          localStorage.setItem('pdffc_tab_' + groupId, idx);
          localStorage.setItem('pdffc_platform', idx);
        } catch(_) {}
      });
    });

    // Restore: use group-specific pref first, then global pref
    try {
      const groupPref  = localStorage.getItem('pdffc_tab_' + groupId);
      const globalPref = localStorage.getItem('pdffc_platform');
      const pref = groupPref !== null ? groupPref : globalPref;
      const idx  = pref !== null ? parseInt(pref) : 0;
      const tabs = tabBar.querySelectorAll('.tool-tab');
      if (idx < tabs.length) tabs[idx].click(); else tabs[0]?.click();
    } catch(_) { tabBar.querySelectorAll('.tool-tab')[0]?.click(); }
  });
}

function initCopyButtons() {
  document.querySelectorAll('.copy-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const pre = btn.closest('.pre-wrap')?.querySelector('pre');
      if (!pre) return;
      navigator.clipboard.writeText(pre.innerText || pre.textContent).then(() => {
        const orig = btn.textContent; btn.textContent = '✓ Copied'; btn.classList.add('copied');
        setTimeout(() => { btn.textContent = orig; btn.classList.remove('copied'); }, 2000);
      }).catch(() => {});
    });
  });
}

function initAnswerReveals() {
  document.querySelectorAll('.reveal-answer-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const box = btn.nextElementSibling; if (!box) return;
      const visible = box.style.display !== 'none';
      box.style.display = visible ? 'none' : 'block';
      btn.textContent = visible ? '👁 Reveal answer' : '🙈 Hide answer';
    });
  });
}

function initAutoComplete(modId, pageId) {
  if (!modId || !pageId || Progress.isPageDone(modId, pageId)) return;
  const handler = () => {
    if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 100) {
      Progress.markPage(modId, pageId); window.removeEventListener('scroll', handler);
    }
  };
  window.addEventListener('scroll', handler, {passive:true});
  document.querySelectorAll('.page-nav .btn').forEach(b => b.addEventListener('click', () => Progress.markPage(modId, pageId)));
}

function initVersionBadge() {
  const cfg = window.COURSE_VERSION;
  if (!cfg) return;
  document.querySelectorAll('.logo-version-badge').forEach(el => {
    el.textContent = 'v' + cfg.version;
    el.title = 'Last updated ' + cfg.date;
  });
}

document.addEventListener('DOMContentLoaded', () => {
  Progress.load(); Progress.updateUI();
  initTabs(); initCopyButtons(); initAnswerReveals(); initVersionBadge();
  const qEl = document.querySelector('.quiz-container[data-mod]');
  if (qEl) Quiz.init(qEl, qEl.dataset.mod);
  const bMod = document.body.dataset.mod, bPage = document.body.dataset.page;
  if (bMod && bPage) initAutoComplete(bMod, bPage);
  const curr = window.location.pathname;
  document.querySelectorAll('.sidebar-item,.sidebar-sub a').forEach(el => {
    const href = el.getAttribute('href') || '';
    if (href && (curr.endsWith(href) || curr.includes(href.replace('../','')))) el.classList.add('active');
  });
  document.querySelector('.btn-reset-progress')?.addEventListener('click', () => {
    if (confirm('Reset all course progress?')) { Progress.reset(); location.reload(); }
  });
});
window.CourseProgress = Progress;
window.CourseQuiz = Quiz;
