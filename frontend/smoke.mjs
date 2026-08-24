/**
 * End-to-end smoke check: signs in, walks every authenticated page, previews a
 * canon-bound prompt and runs the adversarial suite from the UI.
 *
 * This exists because the unit tests mock the API. Driving the real thing is
 * what caught a canon leak between two series that isolated fixtures had hidden
 * for four pull requests: the suite scored 18/18 in pytest and 16/18 here.
 *
 *   BASE=http://127.0.0.1:3001 API_EMAIL=... API_PASSWORD=... \
 *   SHOTS=./shots node smoke.mjs
 *
 * Needs a backend with seeded data and a signed-up user. Screenshots are
 * written only when SHOTS names a directory.
 */
import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';

const BASE = process.env.BASE ?? 'http://127.0.0.1:3001';
const EMAIL = process.env.API_EMAIL;
const PASSWORD = process.env.API_PASSWORD;
const SHOTS = process.env.SHOTS ?? null;

if (!EMAIL || !PASSWORD) {
  console.error('Set API_EMAIL and API_PASSWORD to an account on the target backend.');
  process.exit(2);
}
if (SHOTS) await mkdir(SHOTS, { recursive: true });

const shot = async (page, name, opts = {}) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, ...opts });
};

const errors = [];
// Chromium ships with the container image; PLAYWRIGHT_BROWSERS_PATH points at it.
const launch = process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {};
const browser = await chromium.launch(launch);
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));

let failed = false;
const check = (label, ok, detail = '') => {
  if (!ok) failed = true;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `  ${detail}` : ''}`);
};

try {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await shot(page, '01-login');
  await page.fill('input[name="email"]', EMAIL);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL('**/dashboard', { timeout: 15000 });
  await page.waitForTimeout(2500);
  await shot(page, '02-dashboard');
  check('sign in reaches the dashboard', (await page.locator('h1').first().innerText()) === 'Dashboard');
  console.log('      stat tiles:', await page.locator('section p.tabular-nums').allInnerTexts());

  const pages = [
    ['pipeline', '03-pipeline', 'Pipeline'],
    ['jobs', '04-jobs', 'Jobs'],
    ['generation', '05-generation', 'Prompts and providers'],
    ['evaluation', '06-evaluation', 'Adversarial suite'],
    ['workspaces', '07-workspaces', 'Workspaces'],
  ];
  for (const [route, file, heading] of pages) {
    await page.goto(`${BASE}/${route}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1800);
    await shot(page, file);
    const seen = await page.locator('h1').first().innerText();
    check(`/${route} renders`, seen === heading, seen === heading ? '' : `got "${seen}"`);
  }

  // The join between canon and generation: the rendered prompt must actually
  // carry canon, and must distinguish fixed facts from current ones.
  await page.goto(`${BASE}/generation`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.getByRole('button', { name: /episode_script_v1/ }).click();
  await page.getByRole('button', { name: 'Preview', exact: true }).click();
  await page.waitForTimeout(2000);
  const prompt = await page.locator('pre').last().innerText();
  await shot(page, '08-generation-preview', { fullPage: true });
  check('preview carries the canon block', prompt.includes('ESTABLISHED CANON'));
  check('immutability is marked', prompt.includes('(fixed)'));

  await page.goto(`${BASE}/evaluation`, { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Run suite' }).click();
  await page.waitForTimeout(4000);
  await shot(page, '09-evaluation-run');
  const tiles = await page.locator('section p.tabular-nums').allInnerTexts();
  check('adversarial suite passes through the UI', tiles[0] === '100%', `tiles: ${tiles.join(' ')}`);

  check('no console errors', errors.length === 0, errors.join(' | '));
} finally {
  await browser.close();
}

process.exit(failed ? 1 : 0);
