# Securva Scan API (Cloudflare Worker)

## Deploy in 2 minutes

1. Go to Cloudflare Dashboard > Workers & Pages > Create > Worker
2. Name it: `securva-scan-api`
3. Click "Edit Code"
4. Delete the default code, paste the contents of `scan-api.js`
5. Click "Deploy"
6. Your API is live at: `https://securva-scan-api.<your-subdomain>.workers.dev`

## Update the frontend

In `index.html`, find `WORKER_URL` and set it to your Worker URL:
```js
const WORKER_URL = 'https://securva-scan-api.your-subdomain.workers.dev';
```

## Usage

```
GET https://securva-scan-api.your-subdomain.workers.dev/?url=pejji.com
```

Returns JSON with grade, score, header results, NDPA compliance, cookie security, and TLS info.

## Free tier limits

Cloudflare Workers free: 100,000 requests/day. More than enough.
