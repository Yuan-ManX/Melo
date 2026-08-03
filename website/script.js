/* =========================================================================
   MELO — "Voice as Light" Interactions
   ========================================================================= */
(function () {
  'use strict';

  /* ---------- Nav ---------- */
  const nav = document.getElementById('nav');
  const onScroll = () => nav.classList.toggle('scrolled', window.scrollY > 24);
  window.addEventListener('scroll', onScroll, { passive: true }); onScroll();

  const burger = document.getElementById('navBurger');
  const links = document.querySelector('.nav-links');
  if (burger && links) {
    burger.addEventListener('click', () => {
      const open = burger.classList.toggle('open');
      links.classList.toggle('open', open);
      burger.setAttribute('aria-expanded', String(open));
    });
    links.querySelectorAll('a').forEach((a) => a.addEventListener('click', () => {
      burger.classList.remove('open'); links.classList.remove('open');
      burger.setAttribute('aria-expanded', 'false');
    }));
  }

  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener('click', (e) => {
      const id = a.getAttribute('href');
      if (id === '#' || id.length < 2) return;
      const el = document.querySelector(id);
      if (!el) return;
      e.preventDefault();
      window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 64, behavior: 'smooth' });
    });
  });

  /* ---------- Reveal on scroll ---------- */
  const reveals = Array.from(document.querySelectorAll('.reveal-up, .reveal-fade'));
  if ('IntersectionObserver' in window && reveals.length) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) { entry.target.classList.add('in'); io.unobserve(entry.target); }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
    reveals.forEach((el) => io.observe(el));
  } else { reveals.forEach((el) => el.classList.add('in')); }

  /* ---------- Hero stat count-up ---------- */
  document.querySelectorAll('.stat-n[data-count]').forEach((el) => {
    const target = parseInt(el.dataset.count, 10);
    let started = false;
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting && !started) {
          started = true;
          const dur = 1200; const t0 = performance.now();
          const tick = (t) => {
            const p = Math.min(1, (t - t0) / dur);
            const eased = 1 - Math.pow(1 - p, 3);
            el.textContent = String(Math.round(target * eased));
            if (p < 1) requestAnimationFrame(tick);
            else el.textContent = String(target);
          };
          requestAnimationFrame(tick);
        }
      });
    }, { threshold: 0.5 });
    io.observe(el);
  });

  /* ---------- Voice ribbon (scroll-reactive flowing path) ---------- */
  const ribbonPath = document.getElementById('ribbonPath');
  const ribbonPath2 = document.getElementById('ribbonPath2');
  if (ribbonPath && ribbonPath2) {
    let raf = null;
    const build = (scrollPct) => {
      const w = window.innerWidth, h = window.innerHeight;
      const amp = 60 + scrollPct * 40;
      const phase = scrollPct * Math.PI * 4;
      let d = `M -50 ${h * 0.3}`;
      const steps = 8;
      for (let i = 1; i <= steps; i++) {
        const x = (w / steps) * i;
        const y = h * 0.3 + Math.sin(phase + i * 0.9) * amp;
        d += ` L ${x.toFixed(1)} ${y.toFixed(1)}`;
      }
      return d;
    };
    const build2 = (scrollPct) => {
      const w = window.innerWidth, h = window.innerHeight;
      const amp = 40 + scrollPct * 30;
      const phase = scrollPct * Math.PI * 4 + 1.2;
      let d = `M -50 ${h * 0.7}`;
      const steps = 8;
      for (let i = 1; i <= steps; i++) {
        const x = (w / steps) * i;
        const y = h * 0.7 + Math.cos(phase + i * 0.9) * amp;
        d += ` L ${x.toFixed(1)} ${y.toFixed(1)}`;
      }
      return d;
    };
    const update = () => {
      const sy = window.scrollY;
      const max = Math.max(1, document.body.scrollHeight - window.innerHeight);
      const p = Math.min(1, sy / max);
      ribbonPath.setAttribute('d', build(p));
      ribbonPath2.setAttribute('d', build2(p));
    };
    window.addEventListener('scroll', () => {
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(update);
    }, { passive: true });
    window.addEventListener('resize', update);
    update();
  }

  /* =========================================================================
     i18n — EN / 中文 toggle
     ========================================================================= */
  let currentLang = 'en';

  // Cache English innerHTML on init (the page's default language)
  function cacheEn() {
    document.querySelectorAll('[data-cn-html]').forEach((el) => {
      if (!el.dataset.enHtml) el.dataset.enHtml = el.innerHTML;
    });
  }

  function updateToggleUI() {
    document.querySelectorAll('.lang-opt').forEach((opt) => {
      opt.classList.toggle('active', opt.dataset.lang === currentLang);
    });
  }

  function applyLang(lang) {
    currentLang = lang;
    document.documentElement.lang = lang === 'cn' ? 'zh-CN' : 'en';
    try { localStorage.setItem('melo-lang', lang); } catch (e) {}
    document.querySelectorAll('[data-cn-html]').forEach((el) => {
      el.innerHTML = lang === 'cn' ? el.getAttribute('data-cn-html') : el.dataset.enHtml;
      // After swapping, ensure already-revealed elements stay visible
      el.querySelectorAll('.reveal-up, .reveal-fade').forEach((r) => r.classList.add('in'));
    });
    updateToggleUI();
    restartDemo();
  }

  cacheEn();

  const langToggle = document.getElementById('langToggle');
  if (langToggle) {
    langToggle.addEventListener('click', () => {
      applyLang(currentLang === 'en' ? 'cn' : 'en');
    });
  }

  // Restore saved language (default English)
  let savedLang = 'en';
  try { savedLang = localStorage.getItem('melo-lang') || 'en'; } catch (e) {}
  if (savedLang === 'cn') {
    applyLang('cn');
  } else {
    currentLang = 'en';
    updateToggleUI();
  }

  /* =========================================================================
     Voice Crystallization Demo (bilingual)
     ========================================================================= */
  const crystalStage = document.getElementById('crystalStage');
  const crystalIn = document.getElementById('crystalIn');
  const crystalOut = document.getElementById('crystalOut');
  const coreStatus = document.getElementById('coreStatus');

  // English demo content
  const DEMO_EN = {
    raw: [
      { t: 'so', k: 'f' }, { t: 'um', k: 'f' }, { t: '…', k: 'p' },
      { t: 'I', k: 'w' }, { t: 'was', k: 'w' }, { t: 'thinking', k: 'w' }, { t: ',', k: '.' },
      { t: 'like', k: 'f' }, { t: 'maybe', k: 'w' }, { t: 'we', k: 'w' }, { t: 'could', k: 'w' }, { t: ',', k: '.' },
      { t: 'uh', k: 'f' }, { t: 'ship', k: 'w' }, { t: 'the', k: 'w' }, { t: 'voice', k: 'w' }, { t: 'runtime', k: 'w' },
      { t: 'by', k: 'w' }, { t: ',', k: '.' }, { t: 'you', k: 'f' }, { t: 'know', k: 'f' }, { t: ',', k: '.' },
      { t: 'end', k: 'w' }, { t: 'of', k: 'w' }, { t: 'quarter', k: 'w' }, { t: '?', k: '.' },
      { t: 'I', k: 'w' }, { t: 'mean', k: 'f' }, { t: '…', k: 'p' },
      { t: 'the', k: 'w' }, { t: 'full-duplex', k: 'w' }, { t: 'thing', k: 'w' }, { t: 'is', k: 'w' },
      { t: 'mostly', k: 'w' }, { t: 'working', k: 'w' }, { t: ',', k: '.' },
      { t: 'and', k: 'w' }, { t: ',', k: '.' }, { t: 'uh', k: 'f' }, { t: 'the', k: 'w' }, { t: 'memory', k: 'w' }, { t: 'layer', k: 'w' },
      { t: 'is', k: 'w' }, { t: '…', k: 'p' }, { t: 'yeah', k: 'f' }, { t: ',', k: '.' },
      { t: "it's", k: 'w' }, { t: 'getting', k: 'w' }, { t: 'there', k: 'w' }, { t: '.', k: '.' },
      { t: 'Can', k: 'w' }, { t: 'you', k: 'w' }, { t: 'like', k: 'f' }, { t: 'check', k: 'w' },
      { t: 'with', k: 'w' }, { t: 'the', k: 'w' }, { t: 'team', k: 'w' }, { t: 'and', k: 'w' },
      { t: 'draft', k: 'w' }, { t: 'a', k: 'w' }, { t: 'release', k: 'w' }, { t: 'plan', k: 'w' }, { t: '?', k: '.' }
    ],
    out: [
      'Ship', 'the', 'voice', 'runtime', 'by', 'end', 'of', 'quarter.',
      '\n', 'Full-duplex', 'conversation', 'is', 'functional;', 'the', 'memory', 'layer', 'nears', 'completion.',
      '\n', 'Action:', 'coordinate', 'with', 'the', 'team', 'and', 'draft', 'a', 'release', 'plan.'
    ],
    status: { listening: 'LISTENING', thinking: 'THINKING', speaking: 'SPEAKING', done: 'DONE' },
    spaced: true
  };

  // Chinese demo content
  const DEMO_CN = {
    raw: [
      { t: '那个', k: 'f' }, { t: '…', k: 'p' },
      { t: '我', k: 'w' }, { t: '就在想', k: 'w' }, { t: '，', k: '.' },
      { t: '就是', k: 'f' }, { t: '，', k: '.' },
      { t: '我们', k: 'w' }, { t: '能不能', k: 'w' }, { t: '，', k: '.' },
      { t: '嗯', k: 'f' }, { t: '，', k: '.' },
      { t: '在', k: 'w' }, { t: '这个', k: 'w' }, { t: '季度末', k: 'w' }, { t: '把', k: 'w' },
      { t: '语音', k: 'w' }, { t: '运行时', k: 'w' }, { t: '发布', k: 'w' }, { t: '出去', k: 'w' }, { t: '？', k: '.' },
      { t: '我是说', k: 'f' }, { t: '…', k: 'p' },
      { t: '全双工', k: 'w' }, { t: '那块', k: 'w' }, { t: '基本', k: 'w' }, { t: '能跑了', k: 'w' }, { t: '，', k: '.' },
      { t: '然后', k: 'w' }, { t: '，', k: '.' }, { t: '呃', k: 'f' }, { t: '，', k: '.' },
      { t: '记忆层', k: 'w' }, { t: '也', k: 'w' }, { t: '…', k: 'p' }, { t: '对', k: 'f' }, { t: '，', k: '.' },
      { t: '差不多', k: 'w' }, { t: '快好了', k: 'w' }, { t: '。', k: '.' },
      { t: '你', k: 'w' }, { t: '能不能', k: 'w' }, { t: '就是', k: 'f' }, { t: '跟', k: 'w' },
      { t: '团队', k: 'w' }, { t: '对一下', k: 'w' }, { t: '，', k: '.' },
      { t: '然后', k: 'w' }, { t: '搞个', k: 'w' }, { t: '发布计划', k: 'w' }, { t: '？', k: '.' }
    ],
    out: [
      '本季度末', '发布', '语音', '运行时', '。',
      '\n', '全双工', '对话', '已', '可用', '；', '记忆层', '接近', '完成', '。',
      '\n', '行动', '：', '与', '团队', '对齐', '并', '起草', '发布', '计划', '。'
    ],
    status: { listening: '聆听中', thinking: '思考中', speaking: '表达中', done: '完成' },
    spaced: false
  };

  function getDemo() { return currentLang === 'cn' ? DEMO_CN : DEMO_EN; }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const tokHTML = (tok) => {
    if (tok.k === 'f') return `<span class="c-filler">${tok.t}</span>`;
    if (tok.k === 'p') return `<span class="c-pause">${tok.t}</span>`;
    return `<span>${tok.t}</span>`;
  };
  const spaceFor = (tok, prev, D) => {
    if (!prev) return '';
    if (!D.spaced) return ''; // Chinese: no inter-token spaces
    if (tok.t === ',' || tok.t === '.' || tok.t === '?' || tok.t === '…') return '';
    if (prev.t === ',' || prev.t === '.') return ' ';
    return ' ';
  };

  let demoStarted = false;
  let demoRunId = 0;

  async function run() {
    const myId = ++demoRunId;
    const D = getDemo();
    const mic = crystalIn.querySelector('.mic-pulse');
    crystalIn.innerHTML = '';
    crystalIn.appendChild(mic);
    const cursor = document.createElement('span');
    cursor.className = 'c-cursor';
    crystalIn.appendChild(cursor);
    crystalOut.innerHTML = '';
    coreStatus.textContent = D.status.listening;
    coreStatus.style.color = '#7BA0FF';

    let prev = null;
    for (let i = 0; i < D.raw.length; i++) {
      if (myId !== demoRunId) return;
      const tok = D.raw[i];
      cursor.insertAdjacentHTML('beforebegin', spaceFor(tok, prev, D) + tokHTML(tok));
      prev = tok;
      const delay = tok.k === 'p' ? 340 : tok.k === 'f' ? 140 : 55 + Math.random() * 65;
      await sleep(delay);
      if (myId !== demoRunId) return;
      if (i === Math.floor(D.raw.length * 0.45)) {
        coreStatus.textContent = D.status.thinking;
        coreStatus.style.color = '#D4A04A';
        await sleep(380);
        if (myId !== demoRunId) return;
        coreStatus.textContent = D.status.speaking;
        coreStatus.style.color = '#28c840';
        streamOut(myId, D);
      }
    }
    if (myId !== demoRunId) return;
    await sleep(500);
    if (myId !== demoRunId) return;
    cursor.remove();
    coreStatus.textContent = D.status.done;
    await sleep(2400);
    if (myId !== demoRunId) return;
    if (document.visibilityState === 'visible') run();
  }

  async function streamOut(myId, D) {
    for (const w of D.out) {
      if (myId !== demoRunId) return;
      if (w === '\n') { crystalOut.insertAdjacentHTML('beforeend', '<br/>'); await sleep(100); continue; }
      crystalOut.insertAdjacentHTML('beforeend', `<span>${w}</span>` + (D.spaced ? ' ' : ''));
      await sleep(65 + Math.random() * 55);
    }
  }

  function restartDemo() {
    if (!crystalStage) return;
    demoRunId++; // invalidate any running loop
    demoStarted = true;
    run();
  }

  if (crystalStage && crystalIn && crystalOut && coreStatus) {
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => { if (e.isIntersecting && !demoStarted) { demoStarted = true; run(); } });
      }, { threshold: 0.35 });
      io.observe(crystalStage);
    } else { run(); }
  }

  /* ---------- Models rail drag-to-scroll ---------- */
  const rail = document.getElementById('modelsRail');
  if (rail) {
    let down = false, startX, scrollLeft;
    rail.addEventListener('pointerdown', (e) => {
      down = true; rail.setPointerCapture(e.pointerId);
      startX = e.clientX - rail.offsetLeft; scrollLeft = rail.scrollLeft;
      rail.style.cursor = 'grabbing';
    });
    rail.addEventListener('pointermove', (e) => {
      if (!down) return;
      rail.scrollLeft = scrollLeft - (e.clientX - rail.offsetLeft - startX);
    });
    const end = () => { down = false; rail.style.cursor = ''; };
    rail.addEventListener('pointerup', end); rail.addEventListener('pointercancel', end);
  }

  /* ---------- Nav spy ---------- */
  const sections = Array.from(document.querySelectorAll('section[id]'));
  const navLinkEls = Array.from(document.querySelectorAll('.nav-links a'));
  if (sections.length && navLinkEls.length && 'IntersectionObserver' in window) {
    const spy = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const id = entry.target.id;
          navLinkEls.forEach((a) => { a.style.color = a.getAttribute('href') === '#' + id ? 'var(--ink)' : ''; });
        }
      });
    }, { rootMargin: '-40% 0px -55% 0px' });
    sections.forEach((s) => spy.observe(s));
  }
})();
