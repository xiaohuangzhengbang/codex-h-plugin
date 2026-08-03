export class BitBrowserClient {
  constructor({ apiBaseUrl }) {
    if (!apiBaseUrl) throw new Error('Missing bitbrowser.apiBaseUrl');
    this.apiBaseUrl = apiBaseUrl.replace(/\/+$/, '');
    this.timeoutMs = 45000;
  }

  async post(path, body = {}) {
    const url = `${this.apiBaseUrl}${path}`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    let response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal
      });
    } catch (error) {
      throw new Error(`Cannot connect to BitBrowser local API at ${url}. Check that BitBrowser is open and API service is enabled. ${error.message}`);
    } finally {
      clearTimeout(timeout);
    }

    const text = await response.text();
    let payload;
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = { raw: text };
    }

    if (!response.ok) {
      throw new Error(`BitBrowser API ${path} failed: HTTP ${response.status} ${text}`);
    }

    return payload;
  }

  async health() {
    return this.post('/health');
  }

  async openBrowser({ id, args = [], loadExtensions = true, extractIp = false, queue = true }) {
    if (!id) throw new Error('Missing bitbrowser.browserId');
    const payload = await this.post('/browser/open', {
      id,
      args,
      loadExtensions,
      extractIp,
      queue
    });

    const data = payload.data ?? payload;
    const endpoint = normalizeEndpoint(data.http ?? data.ws ?? data.wsEndpoint ?? data.debuggingAddress);
    if (!endpoint) {
      throw new Error(`BitBrowser did not return a CDP endpoint: ${JSON.stringify(payload)}`);
    }

    return { payload, endpoint };
  }

  async closeBrowser(id) {
    if (!id) return;
    return this.post('/browser/close', { id });
  }

  async listBrowsers(options = {}) {
    const pageSize = Math.min(Number(options.pageSize ?? 100), 100);
    const firstPage = Number(options.page ?? 0);
    const all = [];

    for (let page = firstPage; page < firstPage + 1000; page += 1) {
      const payload = await this.post('/browser/list', {
        page,
        pageSize,
        groupId: options.groupId,
        name: options.name,
        remark: options.remark,
        seq: options.seq,
        minSeq: options.minSeq,
        maxSeq: options.maxSeq,
        sort: options.sort
      });
      const list = extractBrowserList(payload);
      all.push(...list);
      if (list.length < pageSize) break;
    }

    return all;
  }
}

export function normalizeBrowserProfile(profile) {
  return {
    id: profile.id ?? profile.browserId ?? profile.profileId ?? '',
    seq: profile.seq ?? profile.serialNum ?? profile.sequence ?? '',
    name: profile.name ?? '',
    remark: profile.remark ?? '',
    platform: profile.platform ?? '',
    userName: profile.userName ?? profile.username ?? ''
  };
}

function normalizeEndpoint(value) {
  if (!value || typeof value !== 'string') return '';
  if (value.startsWith('ws://') || value.startsWith('wss://')) return value;
  if (value.startsWith('http://') || value.startsWith('https://')) return value;
  return `http://${value}`;
}

function extractBrowserList(payload) {
  const data = payload.data ?? payload;
  if (Array.isArray(data)) return data.map(normalizeBrowserProfile);
  const list = data.list ?? data.records ?? data.items ?? data.data ?? [];
  return Array.isArray(list) ? list.map(normalizeBrowserProfile) : [];
}
