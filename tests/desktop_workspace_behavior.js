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
const transitions=[];
const nodes={'#workspace-nav':{},'#workspace-profile':{},'#top':{closest:()=>({classList:{toggle:(...args)=>transitions.push(args)}})},'#clock':{}};
const test={
  S:{page:'home',snap:{user:{name:'Hamdi <img src=x>'},winctl:true}},
  $:key=>nodes[key]||null, ic:()=>'', hm:()=> '11:40', needCount:()=>2,
  esc:value=>String(value).replace(/</g,'&lt;'), render(){visited.push(test.S.page);},
  store:{set(){}}, toast(){},
};
const visited=[];
vm.createContext(test);
vm.runInContext(slice('const NAV=','function needCount()'),test);
vm.runInContext(slice('function go(p)','function render()'),test);
test.renderTop();
assert.equal(nodes['#top'].innerHTML,'');
assert.deepEqual(transitions.at(-1),['workspace-console',true]);
test.S.page='chat';
test.renderTop();
assert.deepEqual(transitions.at(-1),['workspace-console',false]);
assert(nodes['#workspace-profile'].innerHTML.includes('&lt;img'));
assert(!nodes['#workspace-profile'].innerHTML.includes('<img'));
assert(nodes['#top'].innerHTML.includes('id="clock"'));
test.S.page='home';
for(const route of ['home','chat','files','vision','team','study','tools','settings']){
  assert(nodes['#workspace-nav'].innerHTML.includes('data-go="'+route+'"'));
  test.go(route);
}
assert.deepEqual(visited,['home','chat','files','vision','team','study','tools','settings']);
test.go('menu');assert.equal(test.S.page,'home');
assert(slice('PAGES.home=','ACT.goset=').includes('window.JarvisHome.mount(pg)'));
for(const id of ['compose','home-jobs','news-list','home-messages','home-media']){
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
console.log('Masaüstü gezintisi, profil çıktısı ve eski çizimlerin emekliliği geçti.');
