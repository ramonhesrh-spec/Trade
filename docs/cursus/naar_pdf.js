// Zet docs/cursus/hespulse-cursus.html om naar PDF met de Chromium van Playwright. Eerst: python3 docs/cursus/maak_cursus.py
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const dir = __dirname;
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.goto('file://' + path.join(dir, 'hespulse-cursus.html'));
  await p.pdf({ path: path.join(dir, 'hespulse-cursus.pdf'), format: 'A4', printBackground: true, displayHeaderFooter: true,
    headerTemplate: '<span></span>',
    footerTemplate: '<div style="font-size:8px;width:100%;text-align:center;color:#888">HesPulse cursus · <span class="pageNumber"></span></div>',
    margin: { top: '18mm', bottom: '18mm', left: '16mm', right: '16mm' } });
  await b.close();
  console.log('pdf klaar');
})();
