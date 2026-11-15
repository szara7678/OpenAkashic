import {spawn} from 'node:child_process';
import {readFileSync,writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const browser=spawn('/usr/bin/chromium',['--headless','--no-sandbox','--disable-gpu','--no-proxy-server','--remote-debugging-port=9222','--remote-allow-origins=*','--user-data-dir=/tmp/cedar-qa','about:blank'],{stdio:'ignore'});
let socket;
try {
 let pages;
 for(let attempt=0;attempt<60;attempt++){try{pages=await(await fetch('http://127.0.0.1:9222/json')).json();break;}catch{await new Promise(resolve=>setTimeout(resolve,150));}}
 socket=new WebSocket(pages.find(page=>page.type==='page').webSocketDebuggerUrl);
 await new Promise(resolve=>socket.addEventListener('open',resolve,{once:true}));
 let sequence=0; const pending=new Map(); const errors=[];const requests=[];
 socket.addEventListener('message',event=>{const message=JSON.parse(event.data);if(message.id){const entry=pending.get(message.id);pending.delete(message.id);message.error?entry.reject(message.error):entry.resolve(message.result);}if(message.method==='Runtime.exceptionThrown')errors.push(message.params);if(message.method==='Network.requestWillBeSent')requests.push(message.params.request.url);});
 const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
 const evaluate=async expression=>{const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result.value;};
 await send('Runtime.enable');await send('Network.enable');await send('Page.enable');
 await send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false});
 await send('Page.navigate',{url:'file:///work/index.html'});
 for(let attempt=0;attempt<60;attempt++){if(await evaluate("document.readyState==='complete' && !!document.querySelector('#results')"))break;await new Promise(resolve=>setTimeout(resolve,50));}
 const data=JSON.parse(readFileSync('/task/input/centers.json','utf8'));
 const visible=()=>evaluate("[...document.querySelectorAll('#results [data-center-id]')].filter(card=>!card.hidden).map(card=>card.dataset.centerId)");
 assert.deepEqual(await visible(),data.locations.map(location=>location.id));
 for(const location of data.locations){const text=await evaluate(`document.querySelector('[data-center-id="${location.id}"]').textContent`);for(const value of [location.name,location.neighborhood,...location.services,location.hours,location.note,location.open?'Open':'Closed',location.step_free===true?'Yes':location.step_free===false?'No':'Unknown'])assert(text.includes(value),value);}
 let combinations=0;
 for(const neighborhood of ['', 'East','West','North'])for(const service of ['', 'Cooling','Advice'])for(const step of [false,true]){
 await evaluate(`document.querySelector('#neighborhood').value=${JSON.stringify(neighborhood)};document.querySelector('#service').value=${JSON.stringify(service)};document.querySelector('#step-free').checked=${step};document.querySelector('#service').dispatchEvent(new Event('change',{bubbles:true}));`);
 const active=Boolean(neighborhood||service||step);
 const expected=data.locations.filter(location=>(!active||location.open)&&(!neighborhood||location.neighborhood===neighborhood)&&(!service||location.services.includes(service))&&(!step||location.step_free===true)).map(location=>location.id);
 assert.deepEqual(await visible(),expected);
 assert((await evaluate("document.querySelector('#result-count').textContent")).startsWith(String(expected.length)+' '));
 assert.equal(await evaluate("!document.querySelector('#empty').hidden"),expected.length===0);combinations++;
 }
 await evaluate("document.querySelector('button[type=reset]').click()");assert.equal((await visible()).length,7);
 assert(await evaluate("document.querySelector('#neighborhood').value==='' && document.querySelector('#service').value==='' && !document.querySelector('#step-free').checked"));
 assert(await evaluate("[...document.querySelectorAll('select,input')].every(control=>control.labels.length>0)"));
 const tabKeys=[];await evaluate('document.activeElement.blur()');
 for(let index=0;index<5;index++){await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});tabKeys.push(await evaluate('document.activeElement.id || document.activeElement.textContent.trim()'));assert.equal(await evaluate("getComputedStyle(document.activeElement).outlineStyle"),'solid');}
 assert.deepEqual(tabKeys,['Skip to directory','neighborhood','service','step-free','Reset filters']);
 await evaluate('document.activeElement.blur()');
 const desktop=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});writeFileSync('/work/desktop.png',Buffer.from(desktop.data,'base64'));
 const widths=[];
 for(const width of [390,320,768,1280]){await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});const dimensions=await evaluate('({viewport:innerWidth,scroll:document.documentElement.scrollWidth})');assert(dimensions.scroll<=dimensions.viewport);widths.push(dimensions);if(width===390){const mobile=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});writeFileSync('/work/mobile.png',Buffer.from(mobile.data,'base64'));}}
 assert.equal(errors.length,0);assert.equal(requests.filter(url=>!url.startsWith('file:')&&!url.startsWith('data:')).length,0);
 const report={sourceRecords:data.locations.length,filterCombinations:combinations,cardFields:'all source values verified',reset:'passed',emptyState:'passed',controlLabels:'passed',keyboardOrder:tabKeys,focus:'solid visible outline on all five tab stops',widths,browserExceptions:errors.length,externalRequests:0,screenshots:['desktop.png','mobile.png']};
 writeFileSync('/work/qa-results.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}finally{socket?.close();browser.kill();}
