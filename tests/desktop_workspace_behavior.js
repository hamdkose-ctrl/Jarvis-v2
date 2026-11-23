const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict'), path=require('node:path');
const root=path.join(__dirname,'../webui');
const source=fs.readFileSync(path.join(root,'nx.js'),'utf8');
const entry=fs.readFileSync(path.join(root,'nx.html'),'utf8');
const css=fs.readFileSync(path.join(root,'nx.css'),'utf8');
const consoleCode=fs.readFileSync(path.join(root,'home-console.js'),'utf8');
const slice=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
for(const surface of ['.mnscene','.hscene','.apex-orb','JarvisBackdrop','hologram.js','seljuk-backdrop','renderPageDock']){
  assert(!entry.includes(surface)&&!source.includes(surface)&&!css.includes(surface),surface+' retired');
}
assert(css.includes('/workspace-result.webp'));
assert(fs.existsSync(path.join(root,'workspace-result.webp')));
assert(!fs.existsSync(path.join(root,'home-avatar.webp')));
assert(!source.includes('console-portrait')&&!css.includes('.console-portrait'));
const visited=[];
const test={
  S:{page:'home'},
  render(){visited.push(test.S.page);},
};
vm.createContext(test);
vm.runInContext(slice('const DESKTOP_PAGES=','// GitHub durumu'),test);
vm.runInContext(slice('function go(p)','function render('),test);
assert(!entry.includes('workspace-sidebar'));
assert(!entry.includes('workspace-top'));
assert.match(consoleCode,/id="team-agents"[\s\S]*id="home-workspace"[\s\S]*id="page"/);
for(const route of ['home','chat','vision','team','study','tools','settings']) test.go(route);
assert.deepEqual(visited,['home','home','vision','team','study','tools','settings']);
assert.doesNotMatch(source,/PAGES\.(chat|files)\s*=|id="(clist|fdet|dockhost)"/);
assert.doesNotMatch(css,/\.chatp\b|\.fgrid\b|\.filelist\b/);
test.go('menu');assert.equal(test.S.page,'home');
test.go('files');assert.equal(test.S.page,'home');
assert.doesNotMatch(consoleCode,/data-go="files"|id="office-actions"/);
assert(slice('PAGES.home=','ACT.goset=').includes('window.JarvisHome.mount(pg)'));
for(const id of ['compose','home-expert','news-list','home-messages','home-media']){
  assert(consoleCode.includes('id="'+id+'"'));
}
for(const asset of ['home-console.js','home-console.css','home-console-map.js','home-console-visuals.js']){
  assert(entry.includes('/'+asset));
  assert(fs.existsSync(path.join(root,asset)));
}
assert(entry.includes('/team-center.js'));
assert(entry.includes('data-theme="dark"'));
assert.match(slice('async function drawSettings()', 'function connectionHelpProvider'), /srow\('eye','Görünüm',[^\n]+,theme\)/);
test.document={documentElement:{dataset:{}}};
test.matchMedia=()=>({matches:true});
vm.runInContext(slice('function applyTheme()', '// ======================================================================= veri ve olaylar'),test);
for(const [preference,theme] of [[undefined,'dark'],['dark','dark'],['light','light'],['system','dark']]){
  test.S.ui={nx_theme:preference};
  test.applyTheme();
  assert.equal(test.document.documentElement.dataset.theme,theme);
}
console.log('Uzmanlar sekmeleri ve eski masaüstü kabuğunun kaldırılması doğrulandı.');
