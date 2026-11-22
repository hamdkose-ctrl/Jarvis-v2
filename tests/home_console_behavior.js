const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../webui/nx.js'), 'utf8');
const nodes = new Map();
const listeners = new Map();
const requests = [];
const visited = [];
const snapshot = {
  user: {name: 'Hamdi', slug: 'hamdi'},
  flags: {mic: true},
  all_events: [{title: 'Proje görüşmesi', when: '2099-01-01T14:00'}],
};
const results = {
  send: true,
  snapshot,
  files_list: {files: [
    {name: 'Rapor.pdf', path: '/files/Rapor.pdf', ext: 'pdf', cat: 'pdf', size: 1024, mtime: 1700000000, mine: true},
  ]},
};

const page = {};
const context = vm.createContext({
  URLSearchParams,
  location: {hash: ''},
  document: {
    addEventListener: (type, callback) => {
      listeners.set(type, [...(listeners.get(type) || []), callback]);
    },
    querySelector: selector => nodes.get(selector) || null,
    querySelectorAll: () => [],
  },
  window: {},
  ic: () => '',
  setTimeout: () => 1,
  clearTimeout: () => {},
  fetch: async (url, options) => {
    if (url === '/session') return {ok: true};
    const action = url.split('/').pop();
    assert.ok(Object.hasOwn(results, action), `Unexpected API request: ${action}`);
    requests.push([action, ...JSON.parse(options.body)]);
    return {json: async () => ({ok: true, data: results[action]})};
  },
  snapshot,
  onRender: name => {
    visited.push(name);
    nodes.clear();
    const selectors = name === 'home'
      ? ['#home-messages', '#home-voice', '#home-connection', '#home-calendar', '.console-stage']
      : ['#msgs'];
    for (const selector of [...selectors, '#workspace-nav', '#workspace-profile', '#top']) {
      nodes.set(selector, {innerHTML: '', textContent: '', dataset: {}});
    }
  },
  page,
});
const evaluate = code => vm.runInContext(code, context);
// Use the real click, request, event and message handlers without auto-starting services.
evaluate(source.replace(/\(async function boot\(\)\{[\s\S]*?\}\)\(\);/, ''));
evaluate(`
  S.snap = snapshot;
  S.hist = [];
  S.page = 'home';
  S.day = '2000-01-01';
  render = () => {
    onRender(S.page);
    if (S.page === 'home') PAGES.home(page);
    else if (S.page === 'chat') drawMsgs();
  };
  render();
`);

function click(action, element = {}) {
  const event = {
    target: {closest: selector => selector === '[data-act]' ? {dataset: {act: action}, ...element} : null},
    preventDefault() {},
  };
  for (const listener of listeners.get('click')) listener(event);
}

function send(input) {
  click('send', {closest: selector => selector === '.ask' ? {querySelector: () => input} : null});
}

const flush = () => new Promise(resolve => setImmediate(resolve));
const homeMessages = () => nodes.get('#home-messages').innerHTML;

async function main() {
  assert.match(page.innerHTML, /data-act="homechat"/);
  assert.doesNotMatch(homeMessages(), /Yanıt hazır/);
  assert.equal(nodes.get('#home-voice').textContent, 'Hazır');
  const input = {value: 'Belgeyi özetle'};
  send(input);
  await flush();
  assert.equal(input.value, '');
  assert.equal(evaluate('S.page'), 'home');
  assert.equal(evaluate('S.day'), '2000-01-01');
  assert.deepEqual(visited, ['home']);
  assert.equal(requests.length, 1);
  const [action, text, rid] = requests[0];
  assert.equal(action, 'send');
  assert.equal(text, 'Belgeyi özetle');
  assert.ok(rid);
  assert.match(homeMessages(), /Belgeyi özetle/);
  assert.equal(evaluate('S.waiting'), true);
  assert.equal(nodes.get('.console-stage').dataset.state, 'thinking');

  function emit(kind, text, props = {}) {
    context.message = {k: kind, t: text, user: snapshot.user.slug, rid, ts: Date.now() / 1000, ...props};
    evaluate('onEvent(message)');
  }
  emit('state', 'listening');
  assert.equal(evaluate('S.orb'), 'listening');
  assert.match(nodes.get('#home-voice').textContent, /Dinliyor/);
  assert.equal(nodes.get('.console-stage').dataset.state, 'listening');
  emit('user', text, {mid: 'user-message'});
  assert.equal((homeMessages().match(/Belgeyi özetle/g) || []).length, 1);
  emit('step', 'Belge okundu', {x: 'done|extract'});
  assert.match(homeMessages(), /Belge okundu/);
  emit('assistant', 'Yanıt hazır <metin>', {mid: 'assistant-message'});
  assert.match(homeMessages(), /Yanıt hazır &lt;metin&gt;/);
  assert.equal(evaluate('S.waiting'), false);
  emit('assistant', 'Başka profilin yanıtı', {user: 'different-owner', mid: 'different-message'});
  assert.doesNotMatch(homeMessages(), /Başka profilin/);

  for (const [command, expected] of [
    ['Dosyalarımı göster', /Rapor\.pdf/],
    ['Takvimim', /Proje görüşmesi/],
  ]) {
    await evaluate(`say(${JSON.stringify(command)})`);
    assert.equal(evaluate('S.page'), 'home');
    assert.match(homeMessages(), expected);
  }
  assert.deepEqual(requests.map(([action]) => action), ['send', 'files_list', 'snapshot']);

  click('homechat');
  assert.equal(evaluate('S.page'), 'chat');
  assert.equal(evaluate('S.day'), evaluate('ymd(new Date())'));
  assert.equal(evaluate('S.since'), 0);
  assert.match(nodes.get('#msgs').innerHTML, /Yanıt hazır &lt;metin&gt;/);
  assert.deepEqual(visited, ['home', 'chat']);
  console.log('Ana ekran gönderimi, canlı yanıt, durum ve Sohbete geçiş doğrulandı.');
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
