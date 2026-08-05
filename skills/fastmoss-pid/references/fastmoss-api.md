# FastMoss PID API

- Base URL: `https://openapi.fastmoss.com`
- Method: `POST /product/v1/search`
- Authentication: `Authorization: Bearer <FASTMOSS_API_KEY>`
- Body for one PID:

```json
{
  "filter": {"product_id": "1736655705387075351"},
  "page": 1,
  "pagesize": 1
}
```

`product_id` accepts a string or an array. H always preserves PID as a string. HTTP status must be 200 and JSON `code` must be 0. Read products from `data.list`; retain `request_id` for diagnosis. Primary workflow fields are `product_id`, `title`, and `cover`; other product, sales, GMV, category, shop, and URL fields are retained in the raw result.

Never write the Authorization header or API key to Git, logs, prompts, spreadsheets, or output JSON.

## Network routing

FastMoss OpenAPI may terminate TLS connections from some overseas proxy exits. Treat `SSLEOFError`, `UNEXPECTED_EOF_WHILE_READING`, `ECONNRESET`, and failures before the TLS handshake as network routing errors, not credential errors. If Clash/Mihomo is present and its `DIRECT` delay test succeeds while proxy groups fail, route only `openapi.fastmoss.com` through `DIRECT` and retry once. Keep all other proxy rules unchanged. Never relay the API key through a public proxy.
