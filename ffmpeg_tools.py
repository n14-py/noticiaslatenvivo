# -*- coding: utf-8 -*-
"""Duración, normalizado y miniaturas. Todo el directo sale con el mismo códec."""

import logging
import os
import subprocess

from config import AUDIO_BITRATE, AUDIO_RATE, FPS, RESOLUTION_H, RESOLUTION_W, VIDEO_BITRATE

logger = logging.getLogger(__name__)


def probe_duration(path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        return max(0.5, float(result.stdout.strip()))
    except Exception as exc:
        logger.warning("  [FFprobe] No pude medir %s: %s", path, exc)
        return 0.0


def _run(cmd, timeout):
    return subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout)


def normalize_clip(src, dst):
    """Deja cualquier nota en 720p30 H264 + AAC para poder concatenar en vivo."""
    vf = (
        f"scale={RESOLUTION_W}:{RESOLUTION_H}:force_original_aspect_ratio=decrease,"
        f"pad={RESOLUTION_W}:{RESOLUTION_H}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={FPS},format=yuv420p"
    )
    gop = str(FPS * 2)
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast",
        "-b:v", VIDEO_BITRATE, "-maxrate", VIDEO_BITRATE, "-bufsize", "5000k",
        "-g", gop, "-keyint_min", gop, "-sc_threshold", "0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(AUDIO_RATE), "-ac", "2", "-b:a", AUDIO_BITRATE,
        "-f", "mpegts",
        dst,
    ]
    _run(cmd, timeout=900)
    return os.path.exists(dst) and os.path.getsize(dst) > 1024


def render_voice_bed(visual_path, tts_path, bgm_path, sfx_path, output_path, still_image=False):
    """
    El video (o la placa) lo pone el usuario.
    Acá solo se genera y se mezcla la voz, con música baja y un efecto corto.
    """
    if not visual_path or not os.path.exists(visual_path):
        raise FileNotFoundError(f"No hay video de presentador: {visual_path}")
    if not tts_path or not os.path.exists(tts_path):
        raise FileNotFoundError("No hay audio de voz para mezclar.")

    # El video va en loop. Sin un -t, el filtro no termina nunca.
    voice_seconds = probe_duration(tts_path)
    if voice_seconds < 0.8:
        voice_seconds = 3.0

    cmd = ["ffmpeg", "-y"]
    if still_image:
        cmd += ["-loop", "1", "-i", visual_path]
    else:
        cmd += ["-stream_loop", "-1", "-i", visual_path]
    cmd += ["-i", tts_path]

    voice_label = "a" if not ((bgm_path and os.path.exists(bgm_path)) or (sfx_path and os.path.exists(sfx_path))) else "tts"
    audio_chains = [
        f"[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo,aresample={AUDIO_RATE},volume=1.0[{voice_label}]"
    ]
    mix = []
    next_index = 2

    if bgm_path and os.path.exists(bgm_path):
        cmd += ["-stream_loop", "-1", "-i", bgm_path]
        audio_chains.append(
            f"[{next_index}:a]aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"aresample={AUDIO_RATE},volume=0.12[bgm]"
        )
        mix.append("[bgm]")
        next_index += 1

    if sfx_path and os.path.exists(sfx_path):
        cmd += ["-i", sfx_path]
        audio_chains.append(
            f"[{next_index}:a]aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"aresample={AUDIO_RATE},volume=0.35[sfx]"
        )
        mix.append("[sfx]")

    video_chain = (
        f"[0:v]scale={RESOLUTION_W}:{RESOLUTION_H}:force_original_aspect_ratio=increase,"
        f"crop={RESOLUTION_W}:{RESOLUTION_H}:(iw-ow)/2:(ih-oh)/2,"
        f"fps={FPS},format=yuv420p,setsar=1[v]"
    )
    if not mix:
        filter_complex = video_chain + ";" + audio_chains[0]
    else:
        mix_chain = "[tts]" + "".join(mix) + f"amix=inputs={1 + len(mix)}:duration=first:dropout_transition=0:normalize=0[a]"
        filter_complex = ";".join([video_chain, *audio_chains, mix_chain])

    gop = str(FPS * 2)
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-t", f"{voice_seconds:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-b:v", VIDEO_BITRATE, "-maxrate", VIDEO_BITRATE, "-bufsize", "5000k",
        "-g", gop, "-keyint_min", gop, "-sc_threshold", "0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(AUDIO_RATE), "-ac", "2", "-b:a", AUDIO_BITRATE,
        "-f", "mpegts",
        output_path,
    ]
    try:
        _run(cmd, timeout=180)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode("utf-8", errors="ignore")[-800:]
        logger.error("  [FFmpeg] Falló la mezcla de voz: %s", err)
        raise
    return os.path.exists(output_path) and os.path.getsize(output_path) > 1024


def make_thumbnail(title, subtitle, output_path, font_path):
    """Placa simple para el directo. Si falta la fuente, el vivo sigue igual."""
    font = font_path if font_path and os.path.exists(font_path) else "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    if not os.path.exists(font):
        return False

    def esc(text):
        return (text or "").replace("\\", " ").replace(":", "\\:").replace("'", "")[:70]

    vf = (
        f"drawtext=fontfile='{font}':text='EN VIVO':fontcolor=white:fontsize=42:x=80:y=220,"
        f"drawtext=fontfile='{font}':text='{esc(title)}':fontcolor=white:fontsize=54:x=80:y=290,"
        f"drawtext=fontfile='{font}':text='{esc(subtitle)}':fontcolor=0xF5C518:fontsize=32:x=80:y=380"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x0B1F3A:s={RESOLUTION_W}x{RESOLUTION_H}",
        "-vf", vf,
        "-frames:v", "1",
        output_path,
    ]
    try:
        _run(cmd, timeout=30)
        return os.path.exists(output_path)
    except Exception as exc:
        logger.warning("  [FFmpeg] Miniatura no generada: %s", exc)
        return False


def write_concat_playlist(paths, playlist_path):
    with open(playlist_path, "w", encoding="utf-8") as handle:
        for path in paths:
            safe = os.path.abspath(path).replace("'", r"'\''")
            handle.write(f"file '{safe}'\n")
    return playlist_path
