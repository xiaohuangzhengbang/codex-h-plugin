import { chromium } from 'playwright';
import { BitBrowserClient } from './bitbrowser-client.mjs';
import { AdsPowerClient } from './adspower-client.mjs';

export async function checkTikTokUploadWindows({ config, concurrency, minSeq, maxSeq, names }) {
  const client = config.adspower ? new AdsPowerClient(config.adspower) : new BitBrowserClient(config.bitbrowser);
  await client.health();
  const windows = await client.listBrowsers({
    groupId: config.adspower?.groupId ?? config.bitbrowser?.groupId,
    minSeq,
    maxSeq
  });
  const nameSet = names ? new Set(String(names).split(',').map((item) => item.trim()).filter(Boolean)) : null;
  const minSeqNumber = minSeq == null ? null : Number(minSeq);
  const maxSeqNumber = maxSeq == null ? null : Number(maxSeq);
  const candidates = windows
    .filter((item) => !item.platform || /tiktok/i.test(item.platform))
    .filter((item) => minSeqNumber == null || Number(item.seq) >= minSeqNumber)
    .filter((item) => maxSeqNumber == null || Number(item.seq) <= maxSeqNumber)
    .filter((item) => !nameSet || nameSet.has(item.name) || nameSet.has(String(item.seq)))
    .sort((a, b) => Number(a.seq) - Number(b.seq));

  const perWindowTimeoutMs = Number(config.runtime?.checkTimeoutMs ?? 60000);
  return runWithLimit(candidates, normalizeConcurrency(concurrency ?? config.runtime?.concurrency), (profile) =>
    withTimeout(checkOneWindow({ client, profile, config }), perWindowTimeoutMs, {
      id: profile.id,
      seq: profile.seq,
      name: profile.name,
      remark: profile.remark,
      status: 'timeout',
      reason: `check timed out after ${perWindowTimeoutMs}ms`,
      url: '',
      title: ''
    })
  );
}

async function checkOneWindow({ client, profile, config }) {
  let browser;
  let page;
  try {
    console.log(`[check] opening seq=${profile.seq} name=${profile.name}`);
    const browserConfig = config.adspower ?? config.bitbrowser ?? {};
    const { endpoint } = await client.openBrowser({
      id: profile.id,
      args: browserConfig.openArgs ?? [],
      headless: process.env.ADSPOWER_PUBLISH_HEADLESS === '1' || (config.runtime?.headless ?? false),
      lastOpenedTabs: browserConfig.lastOpenedTabs ?? false,
      proxyDetection: browserConfig.proxyDetection ?? false,
      loadExtensions: browserConfig.loadExtensions ?? true,
      extractIp: browserConfig.extractIp ?? false,
      queue: true
    });
    browser = await chromium.connectOverCDP(endpoint, {
      slowMo: config.runtime?.slowMoMs ?? 0,
      timeout: config.runtime?.timeoutMs ?? 120000
    });
    const context = browser.contexts()[0] ?? await browser.newContext();
    page = await context.newPage();
    await page.goto(config.platform?.uploadUrl ?? 'https://www.tiktok.com/upload', {
      waitUntil: 'domcontentloaded',
      timeout: Math.min(Number(config.runtime?.timeoutMs ?? 120000), Number(config.runtime?.checkTimeoutMs ?? 60000))
    });
    await page.waitForTimeout(7000);
    const snapshot = await page.evaluate(() => ({
      title: document.title,
      url: location.href,
      text: document.body?.innerText?.slice(0, 2000) ?? '',
      fileInputs: document.querySelectorAll('input[type=file]').length,
      buttons: [...document.querySelectorAll('button,[role="button"]')]
        .map((el) => (el.innerText || el.getAttribute('aria-label') || '').trim())
        .filter(Boolean)
        .slice(0, 80)
    }));
    return {
      id: profile.id,
      seq: profile.seq,
      name: profile.name,
      remark: profile.remark,
      status: classifyTikTokUpload(snapshot),
      reason: summarize(snapshot),
      url: snapshot.url,
      title: snapshot.title
    };
  } catch (error) {
    return {
      id: profile.id,
      seq: profile.seq,
      name: profile.name,
      remark: profile.remark,
      status: 'error',
      reason: error.message,
      url: '',
      title: ''
    };
  } finally {
    await page?.close().catch(() => {});
    await browser?.close().catch(() => {});
    if (config.runtime?.closeAfterCheck) {
      await client.closeBrowser(profile.id).catch(() => {});
    }
  }
}

function classifyTikTokUpload(snapshot) {
  const text = `${snapshot.title}\n${snapshot.url}\n${snapshot.text}\n${snapshot.buttons.join('\n')}`;
  if (/captcha|verify you are human|verification|verifica|验证码|安全验证/i.test(text)) return 'verification';
  if (/\/login/i.test(snapshot.url) || /log in|sign in|iniciar sesión|登录/i.test(text)) return 'needs_login';
  if (/\/upload|tiktokstudio\/upload/i.test(snapshot.url)) return 'ready_or_upload_page';
  if (snapshot.fileInputs > 0 || /select video|select file|upload video|post|schedule|cargar/i.test(text)) return 'ready_or_upload_page';
  return 'unknown';
}

function summarize(snapshot) {
  if (/\/login/i.test(snapshot.url)) return 'redirected to TikTok login';
  if (snapshot.fileInputs > 0) return `file input found: ${snapshot.fileInputs}`;
  const buttonHint = snapshot.buttons.find((button) => /upload|post|schedule|select|add link|cargar/i.test(button));
  return buttonHint ? `button found: ${buttonHint}` : snapshot.title;
}

async function runWithLimit(items, limit, worker) {
  const executing = new Set();
  const results = [];
  for (const item of items) {
    const promise = Promise.resolve().then(() => worker(item));
    results.push(promise);
    executing.add(promise);
    promise.finally(() => executing.delete(promise));
    if (executing.size >= Math.max(1, limit)) await Promise.race(executing);
  }
  return Promise.all(results);
}

function normalizeConcurrency(value) {
  const parsed = Number(value ?? 2);
  if (!Number.isFinite(parsed) || parsed < 1) return 1;
  return Math.floor(parsed);
}

function withTimeout(promise, ms, fallback) {
  let timer;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve(fallback), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}
