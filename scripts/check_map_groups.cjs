const { chromium } = require('@playwright/test');
(async () => {
 const browser = await chromium.launch({headless:true,channel:'chrome'});
 const page = await browser.newPage();
 await page.goto('file://' + process.cwd() + '/docs/index.html');
 await page.waitForSelector('#layers-map-1', {timeout:30000});
 for (const [id, name] of [['map-1','MAP-1'], ['map-2','MAP-2'], ['map-1-population','Dân số / xã phường'], ['map-1-facilities','Cơ sở y tế'], ['map-1-routes','Đường phân bổ'], ['map-1-routes-primary','Tuyến chính'], ['map-1-routes-secondary','Tuyến phụ'], ['map-2-children','Trẻ 5–14 tuổi'], ['map-2-schools','Trường học']]) {
  const section = page.locator('section:has(> #layers-' + id + ')');
  const master = section.getByRole('checkbox', {name, exact:true});
  if (await master.getAttribute('aria-checked') === 'true') await master.click();
  await master.click();
  if (await section.locator('input:not(:checked)').count()) throw Error(name+' enable failed '+JSON.stringify(await section.locator('input').evaluateAll(xs=>xs.map(x=>({checked:x.checked, text:x.parentElement.textContent})))));
  await master.click();
  if (await section.locator('input:checked').count()) throw Error(name+' disable failed');
  await section.locator(':scope > div > button[aria-expanded]').click();
  if (await section.locator(':scope > div > button[aria-expanded]').getAttribute('aria-expanded') !== 'false') throw Error('collapse failed');
  await section.locator(':scope > div > button[aria-expanded]').click();
  await section.locator('input').first().check();
  if (await master.getAttribute('aria-checked') !== (await section.locator('input').count() === 1 ? 'true' : 'mixed')) throw Error('mixed state failed');
 }
 console.log('PASS: all 9 nested groups toggle, collapse/expand, individual controls, mixed state');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
