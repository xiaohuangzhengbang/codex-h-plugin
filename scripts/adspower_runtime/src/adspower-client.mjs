export class AdsPowerClient {
  constructor({ apiBaseUrl = 'http://127.0.0.1:50325', apiKey = '', timeoutMs = 45000 } = {}) {
    this.apiBaseUrl = apiBaseUrl.replace(/\/+$/, '');
    this.apiKey = apiKey;
    this.timeoutMs = timeoutMs;
  }

  async request(path, { method = 'GET', body, query } = {}) {
    const url = new URL(`${this.apiBaseUrl}${path}`);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== '' && value != null) url.searchParams.set(key, String(value));
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await fetch(url, {
        method,
        headers: {
          ...(body ? { 'content-type': 'application/json' } : {}),
          ...(this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {})
        },
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal
      });
      const text = await response.text();
      let payload;
      try {
        payload = text ? JSON.parse(text) : {};
      } catch {
        payload = { raw: text };
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${text}`);
      if (payload.code != null && Number(payload.code) !== 0) {
        throw new Error(payload.msg || JSON.stringify(payload));
      }
      return payload;
    } catch (error) {
      throw new Error(`AdsPower API ${method} ${url} failed. Confirm AdsPower is running and Local API is enabled. ${error.message}`);
    } finally {
      clearTimeout(timeout);
    }
  }

  async health() {
    return this.request('/status');
  }

  async openBrowser({ id, profileNo, args = [], headless = false, lastOpenedTabs = false, proxyDetection = false }) {
    if (!id && !profileNo) throw new Error('Missing AdsPower profileId/profileNo');
    const payload = await this.request('/api/v2/browser-profile/start', {
      method: 'POST',
      body: {
        ...(id ? { profile_id: id } : { profile_no: String(profileNo) }),
        launch_args: args,
        headless: headless ? '1' : '0',
        last_opened_tabs: lastOpenedTabs ? '1' : '0',
        proxy_detection: proxyDetection ? '1' : '0'
      }
    });
    const data = payload.data ?? {};
    const endpoint = data.ws?.puppeteer || normalizeEndpoint(data.ws?.selenium || data.debug_port);
    if (!endpoint) throw new Error(`AdsPower did not return a CDP endpoint: ${JSON.stringify(payload)}`);
    return { payload, endpoint };
  }

  async closeBrowser(id) {
    if (!id) return;
    return this.request('/api/v2/browser-profile/stop', {
      method: 'POST',
      body: { profile_id: id }
    });
  }

  async listBrowsers(options = {}) {
    const limit = Math.min(Number(options.pageSize ?? 100), 100);
    const all = [];
    for (let page = Number(options.page ?? 1); page < 1001; page += 1) {
      const payload = await retryRead(() => this.request('/api/v2/browser-profile/list', {
          method: 'POST',
          body: {
            page,
            limit,
            ...(options.groupId ? { group_id: options.groupId } : {}),
            sort_type: options.sortType ?? 'profile_no',
            sort_order: options.sortOrder ?? 'asc'
          }
        }));
      const list = payload.data?.list ?? [];
      all.push(...list.map(normalizeBrowserProfile));
      if (list.length < limit) break;
    }
    return all;
  }
}

export function normalizeBrowserProfile(profile) {
  return {
    id: profile.profile_id ?? '',
    seq: profile.profile_no ?? '',
    name: profile.name ?? '',
    remark: profile.remark ?? '',
    platform: profile.platform ?? '',
    userName: profile.username ?? '',
    groupId: profile.group_id ?? '',
    groupName: profile.group_name ?? ''
  };
}

function normalizeEndpoint(value) {
  if (!value) return '';
  const text = String(value);
  if (/^(ws|wss|http|https):\/\//.test(text)) return text;
  if (/^\d+$/.test(text)) return `http://127.0.0.1:${text}`;
  return `http://${text}`;
}

async function retryRead(fn, attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await new Promise((resolve) => setTimeout(resolve, attempt * 1500));
    }
  }
  throw lastError;
}
