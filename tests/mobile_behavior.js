// Gerçek tarayıcı yerine küçük DOM/HTTP taklitleriyle gönderim ve mikrofon yaşam döngüsü testi.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const pythonSource = fs.readFileSync(path.join(root, 'modules/phone_pages.py'), 'utf8');
const html = require('node:child_process').execFileSync(process.env.JARVIS_TEST_PYTHON||'python',['-c','from modules.phone_pages import PAGE; print(PAGE)'],{cwd:root,encoding:'utf8'});
const js = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const nodes = new Map(), listeners = {}, timerCalls = [], sends = [];
function node(id) {
  if (nodes.has(id)) return nodes.get(id);
  const classes = new Set();
  const n = {id, value: '', children: [], style: {}, textContent: '', innerHTML: '', hidden: false,
    classList: {add: x => classes.add(x), remove: x => classes.delete(x),
      toggle(x, on) { if (on) classes.add(x); else classes.delete(x); }, contains: x => classes.has(x)},
    appendChild(c) { this.children.push(c); }, blur() {}, click() {this.clicked=true;if(this.onclick)this.onclick();},
    showModal() {this.open=true;}, close() {this.open=false;},
    getContext: () => new Proxy({}, { get: (_, k) => k === 'createRadialGradient' ? () => ({addColorStop() {}}) : () => {} })};
  nodes.set(id, n); return n;
}
let uid = 0, recognition, failSend = false, register = '';
class Recognition {
  constructor() { recognition = this; this.aborts = 0; }
  start() { this.onstart(); }
  stop() { if (this.onend) this.onend(); }
  abort() { this.aborts++; if (this.onend) this.onend(); }
}
const document = {hidden: false, body: node('body'), getElementById: node,
  createElement: () => node('generated-' + uid++), createTextNode: text => ({textContent: text}),
  addEventListener: (name, fn) => {listeners[name] = fn;}};
const localStorage = { removeItem(k) { delete this[k]; }, ju: 'Hamdi' };
const context = {document, localStorage, URLSearchParams, URL, Error, console, Date, Math, Promise,
  location: {hash: '#p=once', pathname: '/', origin: 'http://localhost'},
  history: {replaceState() {context.cleaned = true;}},
  navigator: {userAgent: 'iPhone', platform: 'iPhone', serviceWorker: {register: async p => {register = p;}}},
  isSecureContext: true, matchMedia: () => ({matches: false}),
  requestAnimationFrame() {}, setInterval() {}, clearTimeout() {},
  setTimeout(fn, ms) {timerCalls.push(ms); return timerCalls.length;},
  addEventListener(name, fn) {listeners[name] = fn;},
  SpeechRecognition: Recognition,
  speechSynthesis: {cancel() {}, getVoices: () => [], speak() {}},
  SpeechSynthesisUtterance: class {},
  fetch: async (url, options = {}) => {
    if (url === '/api/pair') {
      assert.equal(JSON.parse(options.body).code, 'once');
      return {ok: true, status: 200, json: async () => ({token: 'profile-token'})};
    }
    if (url === '/api/web-session') {
      assert.equal(options.credentials, 'same-origin');
      if(options.method === 'POST') assert.equal(options.headers['X-Token'], 'profile-token');
      else assert.equal(options.headers['X-Jarvis-Web-Session'], '1');
      return {ok: true, json: async () => options.method === 'POST' ? ({ok: true}) : ({token: 'profile-token'})};
    }
    assert.equal(options.headers['X-Token'], 'profile-token');
    if (url === '/api/users') return {ok: true, json: async () => ({list: ['Ebru'], active: 'Ebru'})};
    if (url.startsWith('/api/log')) return {ok: true, json: async () => []};
    if (url === '/api/send') {
      if (failSend) return {ok: false, status: 429};
      sends.push(JSON.parse(options.body));
      return {ok: true, json: async () => ({ok: true})};
    }
    throw Error('Beklenmeyen adres: ' + url);
  }};
context.window = context;
vm.createContext(context);
(async () => {
  vm.runInContext(js, context);
  await new Promise(ok => setImmediate(ok));
  assert.equal(context.cleaned, true);
  assert.equal(localStorage.jk, 'profile-token');
  assert.equal(node('unm').textContent, 'Ebru');
  node('tools-open').onclick();assert.equal(node('tools').open,true);
  node('tool-photo').onclick();assert.equal(node('tools').open,false);assert.equal(node('cam').clicked,true);
  node('tools-open').onclick();node('tool-user').onclick();
  assert.equal(node('tools').open,false);assert.equal(node('sheet').classList.contains('on'),true);
  node('shade').onclick();assert.equal(node('sheet').classList.contains('on'),false);
  node('tools-open').onclick();node('tools-close').onclick();assert.equal(node('tools').open,false);
  node('t').value = 'ilk soru'; failSend = true;
  await node('f').onsubmit({preventDefault() {}});
  assert.equal(node('t').value, 'ilk soru');
  assert.equal(sends.length, 0);
  failSend = false;
  await node('f').onsubmit({preventDefault() {}});
  assert.equal(node('t').value, '');
  assert.equal(sends[0].user, 'Ebru');
  node('mic').onclick();
  assert.equal(node('mic').classList.contains('rec'), true);
  node('t').value = 'gizli sekmede gönderilmez';
  document.hidden = true; listeners.visibilitychange();
  assert.equal(recognition.aborts, 1);
  assert.equal(node('mic').classList.contains('rec'), false);
  assert.equal(sends.length, 1);
  vm.runInContext(fs.readFileSync(path.join(root, 'webui/mobile/install.js'), 'utf8'), context);
  assert.equal(register, '/sw.js');
  await node('install').onclick();
  assert.match(node('toast').textContent, /Ana Ekrana Ekle/);
  const preview=node('preview'),safe='data:image/svg+xml;base64,PHN2Zy8+';
  context.appendChatBody(preview,'Kalıcı tasarım ![Jarvis]('+safe+') devam');
  assert(preview.children.some(n=>n.src===safe));
  const unsafe=node('unsafe');context.appendChatBody(unsafe,'![x](javascript:alert)');assert(!unsafe.children.some(n=>n.src));
  const installed={...context,localStorage:{removeItem(k){delete this[k];}},location:{hash:'',pathname:'/',origin:'https://jarvis.example'}};
  installed.window=installed;vm.createContext(installed);vm.runInContext(js,installed);
  await new Promise(ok=>setImmediate(ok));
  assert.equal(installed.localStorage.jk,'profile-token');
  assert.equal(node('unm').textContent,'Ebru');
  console.log('Mobil davranış: boş uygulama hafızasında oturum geri yükleme,  QR, profil, başarısız/başarılı gönderim, mikrofon kapanması ve iPhone kurulum yönlendirmesi geçti.');
})().catch(e => { console.error(e); process.exitCode = 1; });
