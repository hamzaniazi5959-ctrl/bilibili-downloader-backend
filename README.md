# Bilibili Video Downloader — Backend

Python (FastAPI) + yt-dlp backend that fetches Bilibili video info and streams
merged MP4 downloads. Tested end-to-end locally on 2026-10-07.

## API

| Endpoint | Method | Params | Returns |
|---|---|---|---|
| `/` | GET | — | `{"status":"ok",...}` health check |
| `/api/info` | GET | `url` (bilibili.com / b23.tv link) | title, thumbnail, duration, uploader, view_count, `qualities[]` |
| `/api/download` | GET | `url`, `quality` (360p/480p/720p/1080p, default 720p) | MP4 file download (Content-Disposition attachment) |

Notes:
- CORS is open (`*`) so the static frontend can call it directly.
- Anonymous Bilibili sessions usually cap at 720p; `/api/info` reports only
  qualities the server can actually fetch.
- yt-dlp pulls the clean source stream — no watermark to remove.

## Deploy to Koyeb (free tier, no card needed)

1. Push this folder to a GitHub repo (e.g. `bilibili-downloader-backend`).
2. Sign up / log in at https://koyeb.com (GitHub OAuth is easiest).
3. **Create App → GitHub** → select the repo → Builder: **Dockerfile**
   (auto-detected) → Instance: **free / nano** → Port: **8000**.
4. Set Health check: HTTP, path `/`.
5. Deploy. The public URL looks like
   `https://<app-name>-<org>.koyeb.app`.

## Fallback: Render.com (free tier)

1. Push to GitHub, connect repo at https://render.com — `render.yaml`
   in this folder is auto-detected (Docker, free plan, Singapore).
2. Note: Render free sleeps after 15 min idle (~30s cold start).

## Wire up the frontend

In the "bilibili-video-downloader" web artifact, set the API base URL, e.g.:

```js
const API = "https://<your-app>.koyeb.app";

// 1. Get info
const info = await (await fetch(`${API}/api/info?url=${encodeURIComponent(link)}`)).json();
// info -> { title, thumbnail, duration, qualities: ["1080p","720p",...] }

// 2. Download (use a plain link / window.location so the browser saves the file)
window.location.href = `${API}/api/download?url=${encodeURIComponent(link)}&quality=${q}`;
```

## Local dev

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```
