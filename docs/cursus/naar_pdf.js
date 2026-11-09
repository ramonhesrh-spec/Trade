// Zet de cursus om naar één PDF met de Chromium van Playwright. Eerst: python3 docs/cursus/maak_cursus.py
// De omslag zonder marges en kop, de lessen met kop (logo en titel) en paginanummer; daarna aan elkaar met pypdf (python3).
const { chromium } = require('playwright');
const path = require('path');
const { execFileSync } = require('child_process');
const LOGO = '<svg viewBox="0 0 32 32" width="11" height="11" fill="none" style="vertical-align:-2px;margin-right:5px"><circle cx="16" cy="16" r="15" stroke="#1b2324" stroke-width="2.4"/><path d="M5 16h4l2.5-7 4 14 2.5-7H27" stroke="#1b2324" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
(async () => {
  const dir = __dirname;
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.goto('file://' + path.join(dir, 'omslag.html'));
  await p.pdf({ path: path.join(dir, 'omslag.pdf'), format: 'A4', printBackground: true, margin: { top: '0', bottom: '0', left: '0', right: '0' } });
  await p.goto('file://' + path.join(dir, 'hespulse-cursus.html'));
  await p.pdf({ path: path.join(dir, 'lessen.pdf'), format: 'A4', printBackground: true, displayHeaderFooter: true,
    headerTemplate: '<div style="font-family:Inter,sans-serif;font-size:8px;color:#1b2324;width:100%;padding:0 18mm;display:flex;justify-content:space-between"><span>' + LOGO + '<b>HesPulse</b></span><span style="color:#6b7678">Het model uitgelegd</span></div>',
    footerTemplate: '<div style="font-family:JetBrains Mono,monospace;font-size:8px;color:#6b7678;width:100%;padding:0 18mm;text-align:right"><span class="pageNumber"></span></div>',
    margin: { top: '22mm', bottom: '20mm', left: '18mm', right: '18mm' } });
  await b.close();
  execFileSync('python3', ['-c', `
from pypdf import PdfWriter
w = PdfWriter()
for f in ("omslag.pdf", "lessen.pdf"):
    w.append(f)
w.write("hespulse-cursus.pdf")
import os
for f in ("omslag.pdf", "lessen.pdf"):
    os.remove(f)
`], { cwd: dir });
  console.log('pdf klaar');
})();
