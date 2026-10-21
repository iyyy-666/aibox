const fs = require('fs');
const path = require('path');
const {chromium} = require('C:/Users/iyyy/AppData/Local/npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright');
const web = path.resolve(__dirname, '../../代码/feature_demo/web');
const modules = fs.readFileSync(path.join(__dirname, 'modules.json'), 'utf8');
(async () => {
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage();
  await page.route('http://aibox.local/**', route => {
    const name = new URL(route.request().url()).pathname;
    if (name === '/api/modules') return route.fulfill({contentType:'application/json',body:modules});
    if (name.startsWith('/api/')) return route.fulfill({contentType:'application/json',body:'{"state":"idle"}'});
    const file = name === '/' ? 'index.html' : name.slice(1);
    return route.fulfill({path:path.join(web,file),contentType: file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html'});
  });
  const results = [];
  for (const [width,height] of [[1100,600],[1100,680],[1100,881],[1280,720],[1280,820],[1280,900],[1366,768],[1440,680],[1440,900],[1920,1080]]) {
    await page.setViewportSize({width,height});
    await page.goto('http://aibox.local/');
    await page.waitForSelector('.module-card');
    const metrics = await page.evaluate(() => {
      const rect = e => e.getBoundingClientRect();
      const buttons = [...document.querySelectorAll('.start-button')];
      return {
        count:buttons.length,
        scrollWidth:document.documentElement.scrollWidth,
        scrollHeight:document.documentElement.scrollHeight,
        visible:buttons.every(b => {const r=rect(b);return r.top>=0 && r.bottom<=innerHeight && r.left>=0 && r.right<=innerWidth && r.height>=28;}),
        cardsFit:[...document.querySelectorAll('.module-card')].every(c => c.scrollHeight<=c.clientHeight+1),
        titlesFit:[...document.querySelectorAll('.module-card h3')].every(t => t.scrollHeight<=t.clientHeight && t.scrollWidth<=t.clientWidth),
      };
    });
    results.push({width,height,...metrics});
    if (width === 1280 && height === 720) await page.screenshot({path:path.join(__dirname,process.argv[2] || 'preview.png'), fullPage:true});
  }
  fs.writeFileSync(path.join(__dirname,'checks.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify(results));
  await browser.close();
  if (results.some(r => r.count!==14 || r.scrollWidth>r.width || r.scrollHeight>r.height || !r.visible || !r.cardsFit || !r.titlesFit)) process.exitCode=1;
})();
