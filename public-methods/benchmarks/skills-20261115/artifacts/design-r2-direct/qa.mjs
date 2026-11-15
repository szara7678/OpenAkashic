import fs from 'node:fs';
import assert from 'node:assert/strict';
const targets = await (await fetch('http://localhost:9222/json')).json();
const socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
await new Promise(resolve => socket.addEventListener('open', resolve, {once:true}));
let sequence = 0;
const pending = new Map();
const requests = [];
const errors = [];
socket.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (message.id) { const callback = pending.get(message.id); pending.delete(message.id); callback(message); }
  if (message.method === 'Network.requestWillBeSent') requests.push(message.params.request.url);
  if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails);
});
function call(method, params = {}) {return new Promise((resolve, reject) => {const id = ++sequence; pending.set(id, response => response.error ? reject(response.error) : resolve(response.result)); socket.send(JSON.stringify({id, method, params}));});}
async function evaluate(expression) { const response = await call('Runtime.evaluate', {expression, returnByValue:true}); if(response.exceptionDetails) throw Error(JSON.stringify(response.exceptionDetails)); return response.result.value; }
await call('Page.enable'); await call('Runtime.enable'); await call('Network.enable');
await call('Page.navigate', {url:'file:///work/index.html'});
for (let attempt = 0; attempt < 50; attempt++) { if(await evaluate('document.readyState === "complete" && !!document.getElementById("results")')) break; await new Promise(resolve => setTimeout(resolve,100)); }
const source = JSON.parse(fs.readFileSync('/task/input/centers.json','utf8'));
const visible = 'Array.from(document.querySelectorAll("#results [data-center-id]")).filter(card => !card.hidden).map(card => card.dataset.centerId)';
assert.deepEqual(await evaluate(visible), source.locations.map(location=>location.id));
assert.equal(await evaluate('JSON.stringify(JSON.parse(document.getElementById("source-data").textContent))'), JSON.stringify(source));
for (const location of source.locations) {
 const text = await evaluate(`document.querySelector('[data-center-id="${location.id}"]').textContent`);
 for (const value of [location.name,location.neighborhood,...location.services,location.hours,location.note,location.open?'Open':'Closed',location.step_free===null?'Unknown':location.step_free?'Yes':'No']) assert.ok(text.includes(value), `${location.id}: ${value}`);
}
let combinations = 0;
for (const neighborhood of ['', 'East', 'West', 'North']) for (const service of ['', 'Cooling', 'Advice']) for (const stepFree of [false,true]) {
 await evaluate(`document.getElementById('neighborhood').value=${JSON.stringify(neighborhood)};document.getElementById('service').value=${JSON.stringify(service)};document.getElementById('step-free').checked=${stepFree};document.getElementById('step-free').dispatchEvent(new Event('change',{bubbles:true}));`);
 const active = neighborhood || service || stepFree;
 const expected = source.locations.filter(location => (!active || location.open === true) && (!neighborhood || location.neighborhood === neighborhood) && (!service || location.services.includes(service)) && (!stepFree || location.step_free === true)).map(location=>location.id);
 assert.deepEqual(await evaluate(visible), expected);
 assert.equal(await evaluate('document.getElementById("result-count").textContent'),`${expected.length} ${expected.length===1?'location':'locations'} displayed`);
 assert.equal(await evaluate('document.getElementById("empty").hidden'),expected.length!==0);
 combinations++;
}
await evaluate('document.querySelector("button[type=reset]").click()');
assert.deepEqual(await evaluate(visible), source.locations.map(location=>location.id));
assert.equal(await evaluate('document.getElementById("neighborhood").value + document.getElementById("service").value'), '');
assert.equal(await evaluate('document.getElementById("step-free").checked'),false);
assert.deepEqual(await evaluate('Array.from(document.querySelectorAll("select,input")).map(control=>control.labels[0].textContent.trim().split(/\\s+/).slice(0,control.tagName==="SELECT"?1:2).join(" "))'), ['Neighborhood','Service','Step-free only']);
await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
await call('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
assert.equal(await evaluate('getComputedStyle(document.activeElement).outlineStyle'),'solid');
assert.equal(await evaluate('getComputedStyle(document.activeElement).outlineWidth'),'3px');
const dimensions=[];
for (const [width,height,name] of [[1280,1000,'desktop'],[390,844,'mobile']]) {
 await evaluate('document.activeElement.blur()');
 await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
 assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'),true);
 dimensions.push({width,scrollWidth:await evaluate('document.documentElement.scrollWidth')});
 const shot = await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
 fs.writeFileSync(`/work/${name}.png`,Buffer.from(shot.data,'base64'));
}
assert.deepEqual(errors,[]);
assert.equal(requests.filter(url=>/^https?:/.test(url)).length,0);
const report={combinations,sourceContent:'all seven cards checked',reset:'passed',labels:'passed',keyboardFocus:'3px solid outline',dimensions,externalRequests:0,runtimeErrors:0,screenshots:['desktop.png','mobile.png']};
fs.writeFileSync('/work/qa-results.json',JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
socket.close();
