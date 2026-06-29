from __future__ import annotations
import subprocess
import hashlib
from pathlib import Path
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def timestamped_name(prefix: str, ext: str, ts: Optional[float] = None) -> str:
    import time
    stamp = ts if ts is not None else time.time()
    return f"{prefix}_{int(stamp)}{ext}"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    base = path.stem
    ext = path.suffix
    h = hashlib.sha1(str(path).encode()).hexdigest()[:8]
    return path.with_name(f"{base}_{h}{ext}")


def run_ffmpeg_extract_audio(video_path: Path, out_wav: Path) -> Tuple[bool, str]:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(out_wav),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True, ""
    except FileNotFoundError:
        msg = "ffmpeg not found"
        logger.warning(msg)
        return False, msg
    except subprocess.CalledProcessError as e:
        msg = e.stderr.decode('utf-8', errors='ignore')
        logger.warning("ffmpeg failed: %s", msg)
        return False, msg
