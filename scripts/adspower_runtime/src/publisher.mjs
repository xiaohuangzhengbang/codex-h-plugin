import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import { BitBrowserClient } from './bitbrowser-client.mjs';
import { AdsPowerClient } from './adspower-client.mjs';
import { renderObject, renderTemplate, truthyTemplate } from './template.mjs';

export async function runPublisher({ config, tasks, dryRun = false, taskId = '' }) {
  const selectedTasks = (taskId ? tasks.filter((task) => task.id === taskId) : tasks).map((task) => enrichTask(task, config));
  if (taskId && selectedTasks.length === 0) throw new Error(`No task found with id: ${taskId}`);
  const preflightResults = [];
  const validVideos = [];
  for (const task of selectedTasks) {
    try {
      await validateVideo(task);
      validVideos.push(task);
    } catch (error) {
      preflightResults.push(taskResult(task, 'failed', error));
    }
  }

  const client = createBrowserClient(config);
  await client.health();
  await resolveBrowserReferences(client, validVideos, config);
  const runnable = [];
  for (const task of validVideos) {
    try {
      if (task.resolveError) throw new Error(task.resolveError);
      validateBrowser(task, config);
      runnable.push(task);
    } catch (error) {
      preflightResults.push(taskResult(task, 'failed', error));
    }
  }
  const groups = groupTasksByBrowser(runnable);
  const concurrency = normalizeConcurrency(config.runtime?.concurrency);
  const groupResults = await runWithLimit([...groups.entries()], concurrency, ([browserId, browserTasks]) =>
    runBrowserGroup({ client, browserId, tasks: browserTasks, config, dryRun })
  );
  return [...preflightResults, ...groupResults.flat()];
}

async function runBrowserGroup({ client, browserId, tasks, config, dryRun }) {
  console.log(`[${browserId}] opening browser, tasks: ${tasks.length}`);
  const browserConfig = config.adspower ?? config.bitbrowser;
  const results = [];
  let browser;
  try {
    const { endpoint } = await client.openBrowser({
      id: browserId,
      args: browserConfig.openArgs ?? [],
      headless: process.env.ADSPOWER_PUBLISH_HEADLESS === '1' || (config.runtime?.headless ?? false),
      lastOpenedTabs: browserConfig.lastOpenedTabs ?? false,
      proxyDetection: browserConfig.proxyDetection ?? false,
      loadExtensions: browserConfig.loadExtensions ?? true,
      extractIp: browserConfig.extractIp ?? false,
      queue: browserConfig.queue ?? true
    });
    browser = await chromium.connectOverCDP(endpoint, {
      slowMo: config.runtime?.slowMoMs ?? 0,
      timeout: config.runtime?.timeoutMs ?? 60000
    });
    const context = browser.contexts()[0] ?? await browser.newContext();
    const page = context.pages()[0] ?? await context.newPage();

    for (let index = 0; index < tasks.length; index += 1) {
      const task = tasks[index];
      console.log(`[${browserId}] running task: ${task.id ?? task.videoPath}`);
      try {
        await runTask({ page, config, task, dryRun });
        results.push(taskResult(task, task.publish ? 'published' : 'preview_ready'));
      } catch (error) {
        const manualTakeover = requiresManualTakeover(error);
        results.push(taskResult(task, 'failed', error, manualTakeover));
        if (manualTakeover) {
          for (const pending of tasks.slice(index + 1)) {
            results.push(taskResult(pending, 'skipped', new Error('Profile stopped because login/captcha/risk verification requires manual takeover.'), true));
          }
          break;
        }
      }
    }
  } catch (error) {
    const completed = new Set(results.map((item) => item.id));
    for (const task of tasks) {
      if (!completed.has(task.id ?? task.videoPath)) {
        results.push(taskResult(task, 'failed', error, requiresManualTakeover(error)));
      }
    }
  } finally {
    await browser?.close().catch(() => {});
    if (browserConfig.closeWhenDone) {
      await client.closeBrowser(browserId).catch(() => {});
    }
  }
  return results;
}

function taskResult(task, status, error = null, manualTakeover = false) {
  return {
    id: task.id ?? task.videoPath,
    browserId: task.browserId,
    profileNo: task.browserSeq ?? task.profileNo ?? '',
    videoPath: task.videoPath,
    scheduledAt: task.scheduledAt ?? '',
    timezone: task.timezone ?? '',
    browserTimezone: task.browserTimezone ?? '',
    appliedScheduledAt: task.scheduleDate && task.scheduleTime ? `${task.scheduleDate} ${task.scheduleTime}` : '',
    productPid: task.productPid ?? '',
    status,
    manualTakeover,
    error: error?.message ?? ''
  };
}

function requiresManualTakeover(error) {
  return /captcha|verify you are human|verification|验证码|安全验证|login|sign in|登录|final click occurred|publish_unverified/i.test(error?.message ?? '');
}

async function runTask({ page, config, task, dryRun }) {
  const context = { ...task, platform: config.platform };
  const configuredActions = renderObject(config.platform.flow ?? [], context);
  // Existing workspaces may still contain the legacy English-only flow. TikTok
  // uses the built-in global flow by default so plugin upgrades take effect immediately.
  const actions = config.platform?.name === 'tiktok' && config.platform?.useBuiltInFlow !== false
    ? [{ type: 'tiktokStudioPublish', url: config.platform.uploadUrl, timeoutMs: config.runtime?.timeoutMs ?? 120000 }]
    : configuredActions;
  const artifactsDir = path.resolve(config.runtime?.artifactsDir ?? 'artifacts');
  await fs.mkdir(artifactsDir, { recursive: true });

  for (const [index, action] of actions.entries()) {
    try {
      if (shouldSkip(action, context, dryRun)) continue;
      await runAction(page, action, context);
    } catch (error) {
      const screenshotPath = path.join(artifactsDir, `${safeName(task.browserId)}-${safeName(task.id ?? 'task')}-step-${index + 1}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
      error.message = `${error.message}\nBrowser: ${task.browserId}\nTask: ${task.id ?? '(no id)'}\nStep: ${index + 1} ${JSON.stringify(action)}\nScreenshot: ${screenshotPath}`;
      throw error;
    }
  }
}

async function validateVideo(task) {
  if (!task.videoPath) throw new Error('Task is missing videoPath');
  const absoluteVideoPath = path.resolve(task.videoPath);
  const stat = await fs.stat(absoluteVideoPath).catch(() => null);
  if (!stat?.isFile()) throw new Error(`Video file does not exist: ${absoluteVideoPath}`);
  task.videoPath = absoluteVideoPath;
}

function validateBrowser(task, config) {
  task.browserId = task.browserId || config.adspower?.profileId || config.bitbrowser?.browserId || '';
  if (!task.browserId) {
    throw new Error(`Task ${task.id ?? '(no id)'} is missing browserId/browserSeq/browserName/browserRemark`);
  }
}

function shouldSkip(action, context, dryRun) {
  if (action.when != null && !truthyTemplate(String(action.when), context)) return true;
  if (dryRun && action.type === 'uploadFile') return true;
  if (dryRun && action.type === 'click' && isPublishAction(action)) return true;
  return false;
}

function isPublishAction(action) {
  const selector = `${action.selector ?? ''}`.toLowerCase();
  const text = `${action.text ?? ''}`.toLowerCase();
  return selector.includes('publish') || selector.includes('发布') || text.includes('publish') || text.includes('发布');
}

async function runAction(page, action, context) {
  const timeout = action.timeoutMs ?? 60000;
  const target = action.selector ? page.locator(action.selector).nth(Number(action.nth ?? 0)) : null;

  switch (action.type) {
    case 'goto':
      await page.goto(renderTemplate(action.url, context), { waitUntil: action.waitUntil ?? 'domcontentloaded', timeout });
      break;
    case 'wait':
      await page.waitForTimeout(Number(action.ms ?? 1000));
      break;
    case 'waitForSelector':
      await page.waitForSelector(action.selector, { state: action.state ?? 'visible', timeout });
      break;
    case 'click':
      await withOptional(action, () => target.click({ timeout }));
      break;
    case 'fill':
      await withOptional(action, () => target.fill(action.text ?? '', { timeout }));
      break;
    case 'press':
      await withOptional(action, () => target.press(action.key, { timeout }));
      break;
    case 'check':
      await withOptional(action, () => target.check({ timeout }));
      break;
    case 'uncheck':
      await withOptional(action, () => target.uncheck({ timeout }));
      break;
    case 'selectOption':
      await withOptional(action, () => target.selectOption(action.value, { timeout }));
      break;
    case 'uploadFile':
      await withOptional(action, () => target.setInputFiles(action.path, { timeout }));
      break;
    case 'tiktokStudioPublish':
      await runTikTokStudioPublish(page, context, { ...action, timeout });
      break;
    case 'uploadViaChooser':
      await withOptional(action, async () => {
        const chooserPromise = page.waitForEvent('filechooser', { timeout });
        await target.click({ timeout });
        const chooser = await chooserPromise;
        await chooser.setFiles(action.path);
      });
      break;
    default:
      throw new Error(`Unknown flow action type: ${action.type}`);
  }
}

async function runTikTokStudioPublish(page, task, action) {
  const timeout = action.timeout ?? 120000;
  page.setDefaultTimeout(Math.min(timeout, 30000));
  const uploadUrl = action.url || 'https://www.tiktok.com/tiktokstudio/upload';
  const navigationTimeout = Math.min(timeout, 30000);
  let navigationError;
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      await page.goto(uploadUrl, { waitUntil: 'domcontentloaded', timeout: navigationTimeout });
      navigationError = null;
      break;
    } catch (error) {
      navigationError = error;
      if (attempt === 1) await page.waitForTimeout(500);
    }
  }
  if (navigationError && !page.url().includes('/tiktokstudio/upload')) throw navigationError;
  await assertNoRiskGate(page);

  // TikTok Studio keeps this input hidden; setInputFiles is faster and language-independent.
  const fileInput = await waitForTikTokUploadInput(page, Math.min(timeout, 30000));
  await fileInput.setInputFiles(task.videoPath, { timeout });
  await waitForUploadReady(page, timeout);
  await dismissTikTokTours(page);
  // TikTok may auto-fill the filename shortly after reporting upload complete.
  // Wait for that asynchronous default caption before replacing it.
  await page.waitForTimeout(2500);

  const caption = page.locator("div.public-DraftEditor-content[contenteditable='true'], div[contenteditable='true']").first();
  await caption.click({ timeout });
  await caption.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A');
  await caption.press('Backspace');
  await page.keyboard.insertText(task.description || '');
  await page.keyboard.press('Escape'); // close hashtag/autocomplete overlay before Add link
  await page.waitForTimeout(200);
  const actualCaption = (await caption.innerText()).trim();
  if (actualCaption !== (task.description || '').trim()) throw new Error(`Caption verification failed: ${JSON.stringify(actualCaption)}`);

  if (task.productPid) task.attachedProductName = await attachProductByPid(page, String(task.productPid), timeout);
  if (task.scheduledAt) {
    const schedule = await scheduleForBrowser(page, task.scheduledAt, task.timezone);
    task.browserTimezone = schedule.timezone;
    task.scheduleDate = schedule.date;
    task.scheduleTime = schedule.time;
    await setSchedule(page, schedule.date, schedule.time, timeout);
  }
  await assertNoRiskGate(page);

  if (!task.publish) return;
  await verifyBeforeSubmit(page, task);
  const submit = page.locator("[data-e2e='post_video_button']").first();
  await submit.waitFor({ state: 'visible', timeout });
  if (await submit.isDisabled()) throw new Error('TikTok final publish/schedule button is disabled');
  await submit.click({ timeout }); // Deliberately exactly once. Never retry this click.
  await verifyPublished(page, task, timeout);
}

async function waitForUploadReady(page, timeout) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    await assertNoRiskGate(page);
    const text = await page.locator('body').innerText().catch(() => '');
    if (/Uploaded|Cargado|上传完成|已上传/i.test(text)) return;
    await page.waitForTimeout(1000);
  }
  throw new Error('Video upload did not become ready before timeout');
}

async function waitForTikTokUploadInput(page, timeout) {
  const fileInput = page.locator("input[type='file'][accept*='video']").first();
  const started = Date.now();
  while (Date.now() - started < timeout) {
    await assertNoRiskGate(page);
    if (await fileInput.count()) return fileInput;
    await page.waitForTimeout(250);
  }
  throw new Error('TikTok upload page did not become ready within 30 seconds');
}

async function dismissTikTokTours(page) {
  const overlay = page.locator('[data-test-id="overlay"]:visible');
  if (!(await overlay.count())) return;
  const primary = page.locator('div[class*="tutorial-tooltip__footer"] button:visible, [data-test-id="button-primary"]:visible').last();
  if (await primary.count()) await primary.click({ force: true, timeout: 5000 });
  else await page.keyboard.press('Escape');
  await overlay.waitFor({ state: 'hidden', timeout: 5000 });
}

async function attachProductByPid(page, pid, timeout) {
  const controlTimeout = Math.min(timeout, 15000);
  const addButton = page.locator("[data-e2e='anchor_container'] button:has([data-testid='Plus'])").first();
  if (await addButton.count()) await addButton.click({ timeout: controlTimeout });
  else await page.getByText(ADD_TEXT, { exact: true }).first().click({ timeout: controlTimeout });
  const productOption = page.locator('div.select-option:visible').filter({ hasText: PRODUCT_TEXT }).first();
  await productOption.click({ timeout: controlTimeout });
  const openProductOptions = page.locator('div.select-option:visible');
  if (await openProductOptions.count()) {
    // TikTok Studio's current product selector keeps its option layer open after
    // selection. Close it before clicking Next so the layer cannot intercept the click.
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);
  }
  const productNext = page.getByText(NEXT_TEXT, { exact: true }).first().locator('xpath=ancestor::button[1]');
  await productNext.click({ timeout: controlTimeout, force: (await openProductOptions.count()) > 0 });

  const search = page.locator('input.TUXTextInputCore-input:visible').last();
  await search.fill(pid, { timeout: controlTimeout });
  await search.press('Enter');
  const exact = page.getByText(pid, { exact: true });
  await exact.first().waitFor({ state: 'visible', timeout: controlTimeout });
  const count = await exact.count();
  if (count !== 1) throw new Error(`PID exact-match failed: expected 1 result, found ${count} for ${pid}`);
  const visibleRadios = page.locator('input.TUXRadioStandalone-input:visible');
  if (await visibleRadios.count() !== 1) throw new Error(`PID ${pid} did not resolve to exactly one selectable product`);
  const radio = visibleRadios.first();
  const productName = await radio.getAttribute('value') || pid;
  await exact.first().click({ timeout: controlTimeout });
  if (!(await radio.isChecked())) await radio.evaluate((element) => element.click());
  if (!(await radio.isChecked())) throw new Error(`PID ${pid} exact product row could not be selected`);
  await page.getByText(NEXT_TEXT, { exact: true }).last().locator('xpath=ancestor::button[1]').click({ timeout: controlTimeout });
  const productDialog = page.locator('[role="dialog"]:visible').filter({ has: page.getByText(PRODUCT_NAME_TEXT, { exact: true }) }).last();
  await productDialog.waitFor({ state: 'visible', timeout: controlTimeout });
  const productNameInput = productDialog.locator('input[type="text"]:visible').last();
  await productNameInput.waitFor({ state: 'visible', timeout: controlTimeout });
  let rawDisplayName = '';
  for (let attempt = 0; attempt < 20 && !rawDisplayName.trim(); attempt += 1) {
    rawDisplayName = await productNameInput.inputValue();
    if (!rawDisplayName.trim()) await page.waitForTimeout(100);
  }
  const displayName = tiktokProductDisplayName(rawDisplayName || productName, pid);
  const addProduct = productDialog.getByText(ADD_TEXT, { exact: true }).locator('xpath=ancestor::button[1]');
  let attached = false;
  for (let attempt = 0; attempt < 3 && !attached; attempt += 1) {
    const displayNameReady = await setTikTokProductDisplayName(page, productDialog, productNameInput, displayName, controlTimeout);
    if (!displayNameReady) continue;
    if (await addProduct.isDisabled()) throw new Error(`TikTok rejected product display name: ${JSON.stringify(displayName)}`);
    await addProduct.click({ timeout: controlTimeout });
    await page.waitForTimeout(1500);
    attached = !(await productDialog.isVisible().catch(() => false));
  }
  if (!attached) throw new Error(`TikTok did not confirm product attachment after sanitizing: ${JSON.stringify(displayName)}`);
  await page.getByText(pid, { exact: true }).waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {});
  return displayName;
}

async function setTikTokProductDisplayName(page, productDialog, productNameInput, displayName, timeout) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await productNameInput.click({ timeout });
    await productNameInput.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A');
    await productNameInput.press('Backspace');
    await page.keyboard.insertText(displayName);
    await productNameInput.press('Tab');
    await page.waitForTimeout(500);
    const currentName = await productNameInput.inputValue();
    const invalid = await productNameInput.getAttribute('aria-invalid');
    const invalidMessage = productDialog.getByText(/invalid characters?|caracteres no válidos|caracteres inválidos/i);
    if (currentName === displayName && invalid !== 'true' && !(await invalidMessage.isVisible().catch(() => false))) return true;
  }
  return false;
}

function tiktokProductDisplayName(value, fallback) {
  const clean = String(value || fallback || '')
    .normalize('NFKC')
    .replace(/[^\p{L}\p{N}\s._-]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return Array.from(clean || String(fallback || '')).slice(0, 30).join('');
}

async function setSchedule(page, date, time, timeout) {
  if (!date || !time) throw new Error('scheduledAt must contain YYYY-MM-DD HH:mm');
  const scheduleRadio = page.locator("input[name='postSchedule'][value='schedule']");
  if (!(await scheduleRadio.isChecked().catch(() => false))) {
    await page.getByText(SCHEDULE_TEXT).first().click({ timeout });
  }
  if (!(await scheduleRadio.isChecked())) throw new Error('Could not activate schedule mode');

  const textInputs = page.locator("input[type='text']");
  const values = await textInputs.evaluateAll((els) => els.map((el, i) => ({ i, value: el.value })));
  const dateIndex = values.find((x) => /^\d{4}-\d{2}-\d{2}$/.test(x.value))?.i;
  const timeIndex = values.find((x) => /^\d{2}:\d{2}$/.test(x.value))?.i;
  if (dateIndex == null || timeIndex == null) throw new Error('TikTok schedule controls not found');

  const wantedDay = String(Number(date.slice(-2)));
  await textInputs.nth(dateIndex).click();
  await page.locator('span.day.valid:visible').filter({ hasText: new RegExp(`^${wantedDay}$`) }).click({ timeout });
  const [hour, minute] = time.split(':');
  let actual;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await textInputs.nth(timeIndex).click();
    await page.locator('span.tiktok-timepicker-left:visible').filter({ hasText: new RegExp(`^${hour}$`) }).click({ timeout: Math.min(timeout, 10000) });
    await page.locator('span.tiktok-timepicker-right:visible').filter({ hasText: new RegExp(`^${minute}$`) }).click({ timeout: Math.min(timeout, 10000) });
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);
    actual = { date: await textInputs.nth(dateIndex).inputValue(), time: await textInputs.nth(timeIndex).inputValue() };
    if (actual.date === date && actual.time === time) break;
  }
  if (actual.date !== date || actual.time !== time) throw new Error(`Schedule verification failed: ${JSON.stringify(actual)}`);
}

async function verifyBeforeSubmit(page, task) {
  const body = await page.locator('body').innerText();
  if (task.description && !body.includes(task.description)) throw new Error('Caption verification failed before submit');
  if (task.productPid && task.attachedProductName && !body.includes(task.attachedProductName.slice(0, 20))) {
    throw new Error('Product attachment verification failed before submit');
  }
}

async function verifyPublished(page, task, timeout) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    await assertNoRiskGate(page);
    if (page.url().includes('/tiktokstudio/content')) {
      const body = await page.locator('body').innerText();
      if (!task.description || body.includes(task.description)) return;
    }
    await page.waitForTimeout(1000);
  }
  throw new Error('Final click occurred, but TikTok content-list verification was not obtained; do not retry automatically');
}

async function assertNoRiskGate(page) {
  if (/tiktok\.com\/login(?:[/?#]|$)/i.test(page.url())) {
    throw new Error('TikTok login required in this AdsPower profile; manual takeover required');
  }
  const text = (await page.locator('body').innerText().catch(() => '')).toLowerCase();
  if (/captcha|verify you are human|verifica que eres humano|验证码|安全验证/.test(text)) {
    throw new Error('TikTok login/captcha/risk verification detected; manual takeover required');
  }
}

// Text is only a fallback for controls without stable attributes. The core upload,
// schedule fields, time picker and final button use DOM structure/data-e2e selectors.
const LINK_TEXT = /Add link|Agregar enlace|Adicionar link|Ajouter un lien|Link hinzufügen|Aggiungi link|リンクを追加|링크 추가|添加链接|新增連結|เพิ่มลิงก์|Thêm liên kết|Tambahkan tautan/i;
const PRODUCT_TEXT = /Products?|Productos?|Produtos?|Produits?|Produkte?|Prodotti?|商品|產品|製品|제품|ผลิตภัณฑ์|Sản phẩm|Produk/i;
const PRODUCT_NAME_TEXT = /Product name|Nombre del producto|Nome do produto|Nom du produit|Produktname|Nome prodotto|商品名称|產品名稱|商品名|제품 이름|ชื่อผลิตภัณฑ์|Tên sản phẩm|Nama produk/i;
const NEXT_TEXT = /Next|Siguiente|Próximo|Suivant|Weiter|Avanti|下一步|次へ|다음|ถัดไป|Tiếp theo|Berikutnya/i;
const ADD_TEXT = /Add|Agregar|Adicionar|Ajouter|Hinzufügen|Aggiungi|添加|新增|追加|추가|เพิ่ม|Thêm|Tambahkan/i;
const SCHEDULE_TEXT = /Schedule|Programación|Agendar|Planifier|Zeitplan|Programma|定时发布|排期|予約投稿|예약|กำหนดเวลา|Lên lịch|Jadwalkan/i;

async function withOptional(action, fn) {
  try {
    return await fn();
  } catch (error) {
    if (action.optional) return;
    throw error;
  }
}

function safeName(value) {
  return String(value).replace(/[^\w.-]+/g, '_');
}

function groupTasksByBrowser(tasks) {
  const groups = new Map();
  for (const task of tasks) {
    if (!groups.has(task.browserId)) groups.set(task.browserId, []);
    groups.get(task.browserId).push(task);
  }
  return groups;
}

function enrichTask(task, config) {
  const enriched = { ...task };
  enriched.browserId = enriched.browserId || enriched.profileId || config.adspower?.profileId || config.bitbrowser?.browserId || '';
  enriched.browserSeq = enriched.browserSeq || enriched.profileNo || '';

  if (enriched.scheduledAt) {
    const schedule = parseSchedule(enriched.scheduledAt);
    enriched.scheduleDate = enriched.scheduleDate || schedule.date;
    enriched.scheduleTime = enriched.scheduleTime || schedule.time;
  }

  return enriched;
}

async function resolveBrowserReferences(client, tasks, config) {
  const unresolved = tasks.filter((task) => !task.browserId && (task.browserSeq || task.browserName || task.browserRemark));
  if (unresolved.length === 0) return;

  const windows = await client.listBrowsers({ groupId: config.adspower?.groupId ?? config.bitbrowser?.groupId });
  for (const task of unresolved) {
    const match = findBrowserForTask(task, windows);
    if (!match) {
      task.resolveError = `Cannot match browser profile for task ${task.id ?? '(no id)'}. Use --list-windows to check profileNo/name/remark.`;
      continue;
    }
    task.browserId = match.id;
    task.browserSeq = task.browserSeq || match.seq;
    task.browserName = task.browserName || match.name;
    task.browserRemark = task.browserRemark || match.remark;
  }
}

function createBrowserClient(config) {
  if (config.adspower) return new AdsPowerClient(config.adspower);
  return new BitBrowserClient(config.bitbrowser);
}

function findBrowserForTask(task, windows) {
  if (task.browserSeq) {
    const seq = String(task.browserSeq);
    return windows.find((window) => String(window.seq) === seq);
  }
  if (task.browserName) {
    const name = String(task.browserName);
    return windows.find((window) => window.name === name) ?? windows.find((window) => window.name.includes(name));
  }
  if (task.browserRemark) {
    const remark = String(task.browserRemark);
    return windows.find((window) => window.remark === remark) ?? windows.find((window) => window.remark.includes(remark));
  }
  return null;
}

function parseSchedule(value) {
  const text = String(value).trim();
  const match = text.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
  if (!match) return { date: '', time: '' };
  return { date: match[1], time: match[2] };
}

async function scheduleForBrowser(page, scheduledAt, sourceTimezone) {
  const browserTimezone = await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  const source = String(sourceTimezone || browserTimezone).trim();
  const instant = wallTimeToInstant(scheduledAt, source);
  const parts = datePartsInTimezone(new Date(instant), browserTimezone);
  return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}`, timezone: browserTimezone };
}

function wallTimeToInstant(value, timezone) {
  const match = String(value).trim().match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!match) throw new Error(`Invalid scheduledAt: ${JSON.stringify(value)}`);
  const wanted = match.slice(1).map(Number);
  const wantedUtc = Date.UTC(wanted[0], wanted[1] - 1, wanted[2], wanted[3], wanted[4], 0);
  let instant = wantedUtc;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const parts = datePartsInTimezone(new Date(instant), timezone);
    const represented = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour), Number(parts.minute), 0);
    const correction = wantedUtc - represented;
    instant += correction;
    if (!correction) break;
  }
  return instant;
}

function datePartsInTimezone(date, timezone) {
  const values = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  }).formatToParts(date).filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]));
  return values;
}

async function runWithLimit(items, limit, worker) {
  const executing = new Set();
  const results = [];

  for (const item of items) {
    const promise = Promise.resolve().then(() => worker(item));
    results.push(promise);
    executing.add(promise);
    promise.then(
      () => executing.delete(promise),
      () => executing.delete(promise)
    );

    if (executing.size >= Math.max(1, limit)) {
      await Promise.race(executing);
    }
  }

  return Promise.all(results);
}

function normalizeConcurrency(value) {
  const parsed = Number(value ?? 3);
  if (!Number.isFinite(parsed) || parsed < 1) return 1;
  return Math.floor(parsed);
}
