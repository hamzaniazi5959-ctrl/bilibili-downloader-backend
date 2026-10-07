"""Bilibili video downloader backend.

Endpoints:
  GET  /                -> health check
  GET  /api/info?url=   -> video metadata + available qualities
  GET  /api/download?url=&quality= -> streams the merged MP4 file
"""

import os
import re
import tempfile
from urllib.parse import quote, urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI(title="Bilibili Downloader API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # frontend is a public static page
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

ALLOWED_HOSTS = ("bilibili.com", "b23.tv", "bilibili.tv", "www.bilibili.com")

QUALITY_FORMATS = {
    "360p": "bv*[height<=360]/b[height<=360]/bv*+ba/b",
    "480p": "bv*[height<=480]/b[height<=480]/bv*+ba/b",
    "720p": "bv*[height<=720]/b[height<=720]/bv*+ba/b",
    "1080p": "bv*[height<=1080]/b[height<=1080]/bv*+ba/b",
}

QUALITY_LABELS = ["1080p", "720p", "480p", "360p"]


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Missing url parameter")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        raise HTTPException(
            status_code=400,
            detail="Only bilibili.com / b23.tv links are supported",
        )
    return url


def base_ydl_opts() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "noplaylist": False,
        "http_headers": {
            "Referer": "https://www.bilibili.com",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        },
    }


def first_video(info: dict) -> dict:
    """Flatten playlists/anthologies to the first video entry."""
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise HTTPException(status_code=404, detail="No videos found at this URL")
        return entries[0]
    return info


def detect_qualities(formats: list) -> list:
    """Return available quality labels based on actual stream heights."""
    heights = set()
    for f in formats or []:
        h = f.get("height")
        if h:
            heights.add(h)
    out = []
    for label, cap in (("1080p", 1080), ("720p", 720), ("480p", 480), ("360p", 360)):
        if any(h <= cap for h in heights):
            out.append(label)
    return out or ["360p"]


def safe_filename(title: str, vid: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", (title or "bilibili_video"))[:60].strip()
    return f"{name or 'bilibili_video'} [{vid}].mp4"


@app.get("/")
def health():
    return {"status": "ok", "service": "bilibili-downloader"}


@app.get("/api/info")
def video_info(url: str = Query(..., description="Bilibili video URL")):
    url = validate_url(url)
    try:
        with yt_dlp.YoutubeDL(base_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=502, detail=f"Could not read video: {e}")
    v = first_video(info)
    return {
        "id": v.get("id"),
        "title": v.get("title"),
        "thumbnail": v.get("thumbnail"),
        "duration": v.get("duration"),
        "uploader": v.get("uploader"),
        "view_count": v.get("view_count"),
        "qualities": detect_qualities(v.get("formats")),
        # anonymous sessions usually top out at 720p; 1080p needs login
        "note": "1080p may require login on some videos; available qualities listed are what this server can fetch.",
    }


@app.get("/api/download")
def download_video(
    url: str = Query(..., description="Bilibili video URL"),
    quality: str = Query("720p", description="360p | 480p | 720p | 1080p"),
):
    url = validate_url(url)
    fmt = QUALITY_FORMATS.get(quality, QUALITY_FORMATS["720p"])

    tmpdir = tempfile.mkdtemp(prefix="bili_")
    opts = base_ydl_opts()
    opts.update(
        {
            "format": fmt,
            "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            "merge_output_format": "mp4",
            "postprocessors": [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
            ],
        }
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=502, detail=f"Download failed: {e}")

    v = first_video(info)
    # find the downloaded file
    produced = None
    for root, _, files in os.walk(tmpdir):
        for f in files:
            if f.rsplit(".", 1)[-1].lower() in ("mp4", "mkv", "webm", "mov"):
                produced = os.path.join(root, f)
                break
    if not produced:
        raise HTTPException(status_code=500, detail="Download finished but no file was produced")

    filename = safe_filename(v.get("title"), v.get("id") or "video")
    # HTTP headers must be latin-1; use RFC 5987 for the UTF-8 filename
    ascii_fallback = re.sub(r"[^\x20-\x7e]", "_", filename) or "bilibili_video.mp4"
    content_disposition = (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return FileResponse(
        produced,
        media_type="video/mp4",
        headers={"Content-Disposition": content_disposition},
    )


@app.exception_handler(Exception)
async def unhandled(request, exc):  # noqa: ARG001
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code, content={"error": exc.detail}
        )
    return JSONResponse(status_code=500, content={"error": "Internal server error"})
