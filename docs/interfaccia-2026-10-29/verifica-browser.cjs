const {chromium} = require(process.env.PLAYWRIGHT_MODULE || '../../web/.verifica-ui/testi/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const out = path.join(root, 'docs/interfaccia-2026-10-29');
const records = [];
let checks = 0;
const check = (condition, message) => {assert.ok(condition,message);checks++;};
const base = 'http://127.0.0.1:5182/';
const step = (page, name) => page.locator('.nav').getByRole('button',{name,exact:false}).click();
async function cachedPyodide(context) {
  await context.route('https://cdn.jsdelivr.net/pyodide/**', async route => {
    const name = new URL(route.request().url()).pathname.split('/').at(-1);
    const files = ['web/node_modules/pyodide','web/node_modules/.pyodide-pacchetti'].map(dir=>path.join(root,dir,name));
    const file = files.find(f=>fs.existsSync(f));
    if (!file) {console.log('CDN NON IN CACHE',name);await route.abort();return;}
    await route.fulfill({body:fs.readFileSync(file),headers:{'access-control-allow-origin':'*'},contentType:name.endsWith('.wasm')?'application/wasm':name.endsWith('.mjs')?'text/javascript':name.endsWith('.json')?'application/json':'application/octet-stream'});
  });
}
async function appearance(page, name) {
  await page.evaluate(()=>document.fonts.ready);
  await page.locator('.casa-icon').evaluateAll(images=>Promise.all(images.filter(i=>i.getClientRects().length).map(i=>i.decode())));
  const result = await page.evaluate(()=>{
    const visible = el=>!!el.getClientRects().length;
    const broken=[];
    for(const th of document.querySelectorAll('th')) {
      if(!visible(th))continue;
      const walker=document.createTreeWalker(th,NodeFilter.SHOW_TEXT);
      let node;
      while(node=walker.nextNode())for(const match of node.textContent.matchAll(/\S+/g)) {
        const range=document.createRange();range.setStart(node,match.index);range.setEnd(node,match.index+match[0].length);
        if([...range.getClientRects()].length>1)broken.push(match[0]);
      }
    }
    const orphaned=[];
    for(const anchor of document.querySelectorAll('.info-anchor')){
      if(!visible(anchor))continue;
      const range=document.createRange();range.selectNodeContents(anchor.firstChild);
      const word=range.getBoundingClientRect(),button=anchor.querySelector('.info-trigger').getBoundingClientRect();
      if(!(word.top<button.bottom && word.bottom>button.top))orphaned.push(anchor.textContent);
    }
    return {width:innerWidth,scroll:document.documentElement.scrollWidth,broken,orphaned,theme:document.documentElement.dataset.theme,images:[...document.querySelectorAll('.casa-icon')].filter(visible).map(i=>({src:i.currentSrc,ok:i.complete&&i.naturalWidth>0})),tables:[...document.querySelectorAll('.table-wrap')].filter(visible).map(el=>({client:el.clientWidth,scroll:el.scrollWidth}))};
  });
  check(result.scroll<=result.width, `${name}: pagina larga ${result.scroll}/${result.width}`);
  check(!result.broken.length,`${name}: intestazioni spezzate ${result.broken}`);
  check(!result.orphaned.length,`${name}: (?) isolati ${result.orphaned}`);
  check(result.theme==='light',`${name}: tema chiaro`);
  check(result.images.every(i=>i.ok),`${name}: icone caricate`);
  records.push({name,...result});
  console.log('VISTA',name,JSON.stringify({width:result.width,tables:result.tables.length}));
}
async function screenshot(page, name) {
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,name+'.jpg'),type:'jpeg',quality:78,fullPage:false,scale:'css'});
}
async function popover(page) {
  const tip=page.locator('main .info-trigger').first();
  await tip.focus();await page.keyboard.press('Enter');
  check(await tip.getAttribute('aria-expanded')==='true','Popover da tastiera');
  const id=await tip.getAttribute('aria-controls');
  const box=await page.locator(`[id="${id}"]`).boundingBox();
  const viewport=page.viewportSize();
  check(box && box.x>=0 && box.x+box.width<=viewport.width && box.y>=0 && box.y+box.height<=viewport.height,'Popover nel viewport');
  await page.keyboard.press('Escape');
  check(await tip.getAttribute('aria-expanded')==='false','Esc chiude');
  check(await tip.evaluate(el=>el===document.activeElement),'Esc restituisce focus');
  await tip.click();await page.locator('h1').click();
  check(await tip.getAttribute('aria-expanded')==='false','Clic esterno chiude');
}
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.LOCALAPPDATA+'/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});
 try{
  const context=await browser.newContext({viewport:{width:1400,height:950},deviceScaleFactor:2,serviceWorkers:'block'});
  await cachedPyodide(context);
  const page=await context.newPage();
  const requests=[];context.on('request',r=>requests.push(r.url()));
  const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log('ERRORE PAGINA',e.message)});
  await page.goto(base,{waitUntil:'domcontentloaded'});
  await page.getByRole('button',{name:'Esempio di Torino',exact:true}).waitFor();
  await page.locator('.stato-motore').filter({hasText:'pronto'}).waitFor({timeout:120000});
  console.log('MOTORE PRONTO');
  await appearance(page,'1400-ingresso');await popover(page);await screenshot(page,'1400-ingresso');
  await page.getByRole('button',{name:'Esempio di Torino',exact:true}).click();
  await page.getByLabel('Nome della configurazione').waitFor();
  await page.getByLabel('Nome della configurazione').filter({visible:true}).count();
  await page.waitForFunction(()=>document.querySelector('#nome')?.value.includes('Torino'));
  await page.getByRole('button',{name:'Chiudi il messaggio',exact:true}).click();
  for(const [nav,name] of [['Luogo','luogo'],['Membri e consumi','membri'],['Impianti','impianti'],['Economia','economia'],['Risultati','risultati']]){
    await step(page,nav);await appearance(page,`1400-${name}`);
    check(await page.locator('.topbar button,.topbar .badge').count()===0,`${name}: barra solo titolo`);
    if(name==='luogo')await popover(page);
  }
  check(!requests.some(url=>/MappaTetto|\/leaflet\//.test(url)),'Leaflet non caricato nei passi finché la mappa resta chiusa');
  await step(page,'Impianti');
  await page.getByRole('button',{name:'Apri la foto aerea',exact:true}).click();
  await page.locator('.leaflet-container').waitFor();
  check(requests.some(url=>/MappaTetto/.test(url)),'Mappa caricata solo dopo apertura');
  await appearance(page,'1400-mappa');
  for(const width of [1024,375]){
    await page.setViewportSize({width,height:950});await appearance(page,`${width}-mappa`);
  }
  await page.setViewportSize({width:1400,height:950});await step(page,'Risultati');
  await page.getByRole('button',{name:'Calcola lo scenario',exact:true}).click();
  await page.locator('.kpis .kpi').first().waitFor({timeout:180000});
  console.log('CALCOLO TORINO COMPLETATO');
  await appearance(page,'1400-risultati-calcolati');await screenshot(page,'1400-risultati');
  for(const nav of ['Mese per mese','Flussi di cassa','Sensibilità']) {
    await page.getByRole('button',{name:nav,exact:true}).click();await appearance(page,`1400-grafico-${nav}`);
  }
  const downloadPromise=page.waitForEvent('download');
  await page.locator('main').getByRole('button',{name:'Salva il progetto',exact:true}).click();
  const download=await downloadPromise;
  await download.saveAs(path.join(root,'web/.verifica-ui/torino-salvato.json'));
  const saved=JSON.parse(fs.readFileSync(path.join(root,'web/.verifica-ui/torino-salvato.json')));
  check(!!saved,'Salvataggio JSON letto');
  console.log('SALVATAGGIO',download.suggestedFilename());
  await page.getByRole('button',{name:'Chiudi il messaggio',exact:true}).click();
  for(const width of [1024,375]){
   await page.setViewportSize({width,height:950});
   if(width===1024)await appearance(page,'1024-risultati-calcolati');
   for(const [nav,name] of [['Luogo','luogo'],['Membri e consumi','membri'],['Impianti','impianti'],['Economia','economia'],['Risultati','risultati']]){
    await step(page,nav);await appearance(page,`${width}-${name}`);
    if(name==='membri'){
      const table=page.locator('.table-wrap').first();
      await table.evaluate(el=>el.scrollLeft=300);
      check(await table.evaluate(el=>el.scrollLeft)>0,'Tabella scorre internamente');
      check(await page.evaluate(()=>scrollX)===0,'Pagina ferma durante scroll tabella');
    }
    if(width===375 && name==='impianti')await screenshot(page,'375-impianti');
   }
   if(width===375){
    await popover(page);
    await page.getByRole('button',{name:'Calcola lo scenario',exact:true}).click();
    await page.locator('.kpis .kpi').first().waitFor({timeout:180000});
    await appearance(page,'375-risultati-calcolati');await screenshot(page,'375-risultati');
   }
  }
  page.once('dialog',d=>d.dismiss());await page.getByRole('button',{name:"Torna all'inizio",exact:true}).click();
  check(await page.getByRole('button',{name:'Calcola lo scenario',exact:true}).isVisible(),'Annulla ritorno conserva il passo');
  page.once('dialog',d=>d.accept());await page.getByRole('button',{name:"Torna all'inizio",exact:true}).click();
  await page.getByRole('button',{name:'Riprendi la bozza',exact:true}).waitFor();
  await appearance(page,'375-ingresso');await screenshot(page,'375-ingresso');
  await page.locator('input[type=file][accept=".json,application/json"]').setInputFiles(path.join(root,'web/.verifica-ui/torino-salvato.json'));
  await page.waitForFunction(()=>document.querySelector('#nome')?.value.includes('Torino'));
  check(await page.getByLabel('Nome della configurazione').inputValue()===saved.configurazione?.nome || (await page.getByLabel('Nome della configurazione').inputValue()).includes('Torino'),'Reimportazione salvataggio');
  const radio=page.getByRole('radio',{name:'Gruppo di autoconsumatori (condominio)',exact:true});
  const tip=page.getByRole('button',{name:'Spiegazione: Gruppo di autoconsumatori (condominio)',exact:true});
  check(!await radio.isChecked(),'Torino parte come CER');
  await tip.click();check(!await radio.isChecked(),'Il (?) della configurazione non cambia il radio');
  await page.keyboard.press('Escape');
  await step(page,'Membri e consumi');
  const firstName=page.getByLabel('Contatore, riga 1',{exact:true});await firstName.fill('Famiglia_2');
  await page.locator('.issue-errors').filter({hasText:'Contatori da completare'}).waitFor();
  check(await page.locator('.issue-errors').filter({hasText:'Contatori da completare'}).isVisible(),'Errori bloccanti aperti');
  await page.getByRole('button',{name:'Salva il progetto',exact:true}).click();
  await page.locator('.notice').filter({hasText:'Il lavoro non si può ancora salvare:'}).first().waitFor();
  check(await page.locator('.issue-errors').filter({hasText:'Dati da completare'}).isVisible(),'Salvataggio bloccato dai controlli originali del motore');
  await appearance(page,'375-errori-contatori');
  await firstName.fill('Famiglia_1');
  check(errors.length===0,`Nessun errore JavaScript: ${errors}`);
  await context.close();
  // Scheda separata: nessuna richiesta al motore né alla mappa quando si apre o compila.
  const family=await browser.newContext({viewport:{width:1400,height:950},deviceScaleFactor:2});
  const familyRequests=[];family.on('request',r=>familyRequests.push(r.url()));
  const p=await family.newPage();await p.goto(base+'?modulo=famiglia&per=Comunit%C3%A0%20Torino');
  await p.locator('#membro').fill('Famiglia Rossi');await p.locator('#c0-kwh').fill('2700');
  await p.locator('#c0-f1').fill('900');await p.locator('#c0-f23').fill('1800');
  await appearance(p,'1400-famiglia');await popover(p);await screenshot(p,'1400-famiglia');
  await p.setViewportSize({width:375,height:950});await appearance(p,'375-famiglia');await screenshot(p,'375-famiglia');
  check(!familyRequests.some(url=>/pyodide|worker\.ts|motore\/|MappaTetto|leaflet|App\.tsx/.test(url)),'Scheda senza motore o Leaflet');
  const filePromise=p.waitForEvent('download');await p.getByRole('button',{name:'Scarica la scheda',exact:true}).click();
  const file=await filePromise;await file.saveAs(path.join(root,'web/.verifica-ui/famiglia.json'));
  const schema=JSON.parse(fs.readFileSync(path.join(root,'web/.verifica-ui/famiglia.json')));check(!!schema,'Scheda salvata');
  console.log('SCHEDA LEGGERA',familyRequests.length,'richieste');
  await family.close();
 }finally{await browser.close();fs.writeFileSync(path.join(out,'verifica-browser.json'),JSON.stringify({checks,records},null,2));console.log('CONTROLLI',checks);}
})().catch(e=>{console.error(e);process.exitCode=1});
