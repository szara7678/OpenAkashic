const { chromium } = require('/opt/eval-browser/node_modules/playwright-core');
const fs = require('fs');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({executablePath:'/usr/bin/chromium', headless:true, args:['--no-sandbox']});
  const page = await browser.newPage({viewport:{width:1280,height:1000}});
  const errors = [], network = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('request', request => { if (/^https?:/.test(request.url())) network.push(request.url()); });
  await page.goto('file:///work/index.html');
  const source = JSON.parse(fs.readFileSync('/task/input/centers.json','utf8'));
  const displayed = () => page.locator('#results [data-center-id]').evaluateAll(cards => cards.map(card => card.dataset.centerId));
  assert.deepEqual(await displayed(),source.locations.map(center => center.id));
  for (const center of source.locations) {
    const text = await page.locator(`[data-center-id="${center.id}"]`).innerText();
    for (const value of [center.name, center.neighborhood, ...center.services, center.hours, center.note, center.open ? 'Open' : 'Closed', center.step_free === null ? 'Unknown' : center.step_free ? 'Yes' : 'No']) assert(text.includes(value), `${center.id}: ${value}`);
  }
  assert.equal(await page.locator('time').getAttribute('datetime'),source.snapshot_date);
  await page.screenshot({path:'/work/desktop.png',fullPage:true});
  let combinations = 0;
  for (const neighborhood of ['', 'East','West','North']) for (const service of ['', 'Cooling','Advice']) for (const stepFree of [false,true]) {
    await page.getByLabel('Neighborhood',{exact:true}).selectOption(neighborhood);
    await page.getByLabel('Service',{exact:true}).selectOption(service);
    await page.getByLabel('Step-free only',{exact:true}).setChecked(stepFree);
    const active = Boolean(neighborhood || service || stepFree);
    const expected = source.locations.filter(center => (!active || center.open) && (!neighborhood || center.neighborhood === neighborhood) && (!service || center.services.includes(service)) && (!stepFree || center.step_free === true));
    assert.deepEqual(await displayed(),expected.map(center => center.id));
    assert.match(await page.locator('#result-count').innerText(),new RegExp(`^${expected.length} `));
    assert.equal(await page.getByRole('heading',{name:'No matching open locations'}).count(),expected.length ? 0 : 1);
    combinations++;
  }
  await page.getByRole('button',{name:'Reset filters',exact:true}).click();
  assert.deepEqual(await displayed(),source.locations.map(center => center.id));
  assert.equal(await page.getByLabel('Neighborhood',{exact:true}).inputValue(),'');
  assert.equal(await page.getByLabel('Service',{exact:true}).inputValue(),'');
  assert.equal(await page.getByLabel('Step-free only',{exact:true}).isChecked(),false);
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  for (const element of await page.locator('select, input, button').all()) {
    const box = await element.boundingBox();
    assert(box.x >= 0 && box.x + box.width <= 390);
  }
  await page.screenshot({path:'/work/mobile.png',fullPage:true});
  await page.reload();
  await page.keyboard.press('Tab');
  assert.equal(await page.locator(':focus').innerText(),'Skip to directory');
  await page.keyboard.press('Tab');
  assert.equal(await page.locator(':focus').getAttribute('id'),'neighborhood');
  assert.equal(await page.locator(':focus').evaluate(element => getComputedStyle(element).outlineStyle),'solid');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  assert.equal(await page.getByLabel('Neighborhood',{exact:true}).inputValue(),'East');
  assert.deepEqual(await displayed(),['cedar-library','market-room']);
  await page.getByLabel('Service',{exact:true}).selectOption('Cooling');
  await page.getByLabel('Step-free only',{exact:true}).check();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.getByLabel('Neighborhood',{exact:true}).selectOption('West');
  await page.getByLabel('Service',{exact:true}).selectOption('Advice');
  assert.equal((await displayed()).length,0);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({path:'/work/empty-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
  assert.deepEqual(network,[]);
  const report = {status:'PASS',combinations,initialLocations:source.locations.length,reset:'PASS',sourceFields:'PASS',snapshotDate:'PASS',keyboard:'Tab reaches skip link and Neighborhood; visible solid focus; arrow selection updates results',mobileOverflow:'none at 390px, default, filtered and empty states',externalRequests:network.length,pageErrors:errors.length};
  fs.writeFileSync('/work/qa-results.json',JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
  await browser.close();
})().catch(error => {console.error(error);process.exit(1);});
