'use strict';
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const demo = document.querySelector('.demo');
const playback = document.querySelector('#playback');
const command = document.querySelector('#demo-command');
const result = document.querySelector('#demo-result');
const branch = document.querySelector('#preview-branch');
const live = document.querySelector('#live-label');
const scenes = [
  {command: 'spotlight on', result: 'Worktree attached.', branch: 'feature/payments', live: 'Live preview'},
  {command: 'spotlight on feature/navigation', result: 'Worktree switched.', branch: 'feature/navigation', live: 'Live preview'},
  {command: 'spotlight off', result: 'Original files restored.', branch: 'main', live: 'Restored'},
];
let current = 0;
let playing = !reducedMotion.matches;
let timer;
function renderScene(index) {
  current = index;
  demo.dataset.scene = index;
  const scene = scenes[index];
  command.textContent = scene.command;
  result.textContent = scene.result;
  branch.textContent = scene.branch;
  live.textContent = scene.live;
  document.querySelectorAll('[data-select]').forEach(button => {
    const selected = Number(button.dataset.select) === index;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  demo.classList.remove('is-changing');
  void demo.offsetWidth;
  demo.classList.add('is-changing');
  const progress = document.querySelector('.demo-progress span');
  progress.getAnimations().forEach(animation => { animation.currentTime = 0; });
}
function schedule() {
  clearInterval(timer);
  demo.classList.toggle('paused', !playing || document.hidden);
  playback.innerHTML = playing ? 'Pause <span aria-hidden="true">Ⅱ</span>' : 'Play <span aria-hidden="true">▷</span>';
  playback.setAttribute('aria-label', playing ? 'Pause animation' : 'Play animation');
  if (playing && !document.hidden) timer = setInterval(() => renderScene((current + 1) % scenes.length), 5000);
}
document.querySelectorAll('[data-select]').forEach(button => button.addEventListener('click', () => {
  playing = false;
  renderScene(Number(button.dataset.select));
  schedule();
}));
playback.addEventListener('click', () => { playing = !playing; schedule(); });
document.addEventListener('visibilitychange', schedule);
reducedMotion.addEventListener('change', () => { if (reducedMotion.matches) playing = false; schedule(); });
schedule();
if (!reducedMotion.matches && 'IntersectionObserver' in window) {
  document.documentElement.classList.add('js-motion');
  const observer = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) { entry.target.classList.add('visible'); observer.unobserve(entry.target); }
  }), {threshold: .1});
  document.querySelectorAll('.reveal').forEach(item => observer.observe(item));
}
if (window.matchMedia('(pointer: fine)').matches) {
  demo.addEventListener('pointermove', event => {
    if (reducedMotion.matches) return;
    const rect = demo.getBoundingClientRect();
    demo.style.setProperty('--ry', `${((event.clientX - rect.left) / rect.width - .5) * 2}deg`);
    demo.style.setProperty('--rx', `${-((event.clientY - rect.top) / rect.height - .5) * 2}deg`);
  });
  demo.addEventListener('pointerleave', () => { demo.style.setProperty('--ry', '0deg'); demo.style.setProperty('--rx', '0deg'); });
}
const tools = { t3: 'T3 CODE', herdr: 'HERDR', conductor: 'CONDUCTOR', git: 'PLAIN GIT' };
const toolInstructions = {
  t3: 'Use the terminal in your task’s worktree. Run Spotlight, then test in the main checkout.',
  herdr: 'Use the worktree Herdr created for your task. Run Spotlight, then test in the main checkout.',
  conductor: 'Turn off Conductor’s built-in Spotlight first. Then run this in your workspace terminal.',
  git: 'Create a worktree with git worktree add, then open a terminal inside it and run Spotlight.',
};
const tabs = [...document.querySelectorAll('[data-tool]')];
function activateTab(tab) {
  tabs.forEach(button => { const selected = button === tab; button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1; });
  document.querySelector('#tool-label').textContent = `WORKING IN ${tools[tab.dataset.tool]}`;
  document.querySelector('#tool-panel h3 + p').textContent = toolInstructions[tab.dataset.tool];
  document.querySelector('#tool-panel').setAttribute('aria-labelledby', tab.id);
}
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => activateTab(tab));
  tab.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    if (next !== undefined) { event.preventDefault(); activateTab(tabs[next]); tabs[next].focus(); }
  });
});
let toastTimer;
document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  const text = document.getElementById(button.dataset.copy).textContent.trim();
  const status = document.querySelector('#copy-status');
  try {
    await navigator.clipboard.writeText(text);
    status.textContent = 'Copied. Ready for your terminal or agent.';
  } catch {
    const range = document.createRange();
    range.selectNodeContents(document.getElementById(button.dataset.copy));
    const selection = window.getSelection();
    selection.removeAllRanges(); selection.addRange(range);
    status.textContent = 'Text selected. Press ⌘C or Ctrl+C to copy.';
  }
  status.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => status.classList.remove('show'), 3200);
}));
document.querySelectorAll('.mobile-nav a').forEach(link => link.addEventListener('click', () => document.querySelector('.mobile-nav').removeAttribute('open')));
