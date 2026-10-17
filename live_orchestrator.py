# -*- coding: utf-8 -*-
"""
Arma el directo y lo empuja a YouTube en tiempo real.

1. Agrupa las notas del país.
2. Genera solo la voz de la intro, los cambios de bloque y la despedida.
3. Esa voz entra encima del video de presentador que deja el usuario.
4. Las noticias se reproducen tal cual llegaron (ya vienen hechas por TTS-FMPEG).
5. Se abre el vivo, se activa la pauta y se transmite por RTMP.
"""

import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from urllib.parse import unquote, urlparse
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from config import (
    AD_CUEPOINT_SECONDS,
    AD_MIN_GAP_SECONDS,
    ADMIN_API_KEY,
    CANAL_DEFAULT,
    COUNTRIES,
    COUNTRY_NAME_TO_CODE,
    FONT_PATH,
    LOCKS_DIR,
    MAIN_API_URL,
    OUTRO_IMAGE,
    TEMP_VIDEO_DIR,
    canal_nombre,
    requested_account,
)
from ffmpeg_tools import (
    make_thumbnail,
    normalize_clip,
    probe_duration,
    render_voice_bed,
    write_concat_playlist,
)
from media_manager import download_media, get_random_bgm, get_random_sfx, get_random_template
from rundown_builder import PayloadError, build_rundown, extract_videos
from script_director import choose_anchor, compose
from youtube_live import YouTubeLiveSession

logger = logging.getLogger(__name__)

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

_state_lock = threading.Lock()
STATE = {
    "status": "idle",
    "live_id": None,
    "pais": None,
    "canal": None,
    "cuenta": None,
    "title": None,
    "youtube_id": None,
    "watch_url": None,
    "monetization_enabled": False,
    "error": None,
    "video_count": 0,
    "started_at": None,
}

_control_lock = threading.Lock()
_stop_event = threading.Event()
_ffmpeg_proc = None


def snapshot():
    with _state_lock:
        return dict(STATE)


def _set_state(**kwargs):
    with _state_lock:
        STATE.update(kwargs)


def request_stop():
    _stop_event.set()
    proc = _ffmpeg_proc
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
    return snapshot()


def _already_done(live_id):
    return os.path.exists(os.path.join(LOCKS_DIR, f"{live_id}.done"))


def _mark_done(live_id, youtube_id):
    path = os.path.join(LOCKS_DIR, f"{live_id}.done")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat()} {youtube_id}\n")


def resolve_country(payload):
    raw = str(payload.get("pais") or payload.get("country") or payload.get("pais_codigo") or "").strip().lower()
    code = raw if raw in COUNTRIES else COUNTRY_NAME_TO_CODE.get(raw)
    if code and code in COUNTRIES:
        info = COUNTRIES[code]
        nombre = payload.get("pais_nombre") or info["nombre"]
        return code, nombre, info["tz"]
    nombre = payload.get("pais_nombre") or (raw.capitalize() if raw else "Latinoamérica")
    return raw or "latam", nombre, "America/Asuncion"


def _clock(tz_name):
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now = datetime.now(ZoneInfo("America/Asuncion"))
    fecha_larga = f"{DIAS[now.weekday()]} {now.day} de {MESES[now.month - 1]} de {now.year}"
    fecha_corta = f"{now.day} de {MESES[now.month - 1]}"
    return now, fecha_larga, fecha_corta


def prepare_show(payload, rng, with_script=True):
    """Valida y ordena. El guion (Gemini) solo se pide si with_script es verdadero."""
    videos, explicit = extract_videos(payload)
    code, nombre, tz_name = resolve_country(payload)
    now, fecha_larga, fecha_corta = _clock(tz_name)
    rundown = build_rundown(videos, explicit_blocks=explicit)
    if not rundown["blocks"]:
        raise PayloadError("No quedaron bloques para emitir.")

    try:
        cuenta = requested_account(payload)
    except ValueError as exc:
        raise PayloadError(str(exc)) from exc
    voice_key = payload.get("voz") or payload.get("voice")
    anchor = choose_anchor(rng, voice_key=voice_key)
    canal = str(payload.get("canal") or "").strip()
    if not canal:
        canal = canal_nombre(cuenta) if cuenta is not None else CANAL_DEFAULT
    meta = {
        "canal": canal,
        "pais_codigo": code,
        "pais_nombre": nombre,
        "fecha_larga": fecha_larga,
        "fecha_corta": fecha_corta,
        "video_count": rundown["video_count"],
        "tz": tz_name,
    }
    package = compose(meta, rundown["blocks"], anchor, rng) if with_script else None
    live_id = str(
        payload.get("live_id")
        or payload.get("liveId")
        or f"{code}-{now.strftime('%Y%m%d-%H%M')}-{uuid.uuid4().hex[:4]}"
    )
    return {
        "live_id": live_id,
        "meta": meta,
        "rundown": rundown,
        "anchor": anchor,
        "package": package,
        "privacy": payload.get("privacy") or payload.get("privacidad"),
        "cuenta": cuenta,
    }


def _pick_visual(kind, gender, rng):
    if kind == "intro":
        visual = get_random_template("intros", rng)
        if visual:
            return visual, False
    if kind == "outro":
        visual = get_random_template("outros", rng)
        if visual:
            return visual, False
        if os.path.exists(OUTRO_IMAGE):
            return OUTRO_IMAGE, True
    visual = get_random_template(gender, rng)
    if visual:
        return visual, False
    visual = get_random_template("intros", rng)
    if visual:
        return visual, False
    if os.path.exists(OUTRO_IMAGE):
        return OUTRO_IMAGE, True
    return None, False


def _render_spoken(kind, text, anchor, rng, workdir, index):
    from tts_engine import generate_audio_clip

    filename = f"{kind}_{index}.mp3"
    # El TTS guarda en TEMP_AUDIO_DIR. Después el renderer lee esa ruta.
    audio = generate_audio_clip(text, anchor["voice_key"], filename, rate=anchor["rate"])
    if not audio:
        raise RuntimeError(f"No se pudo generar la voz de {kind}.")
    visual, still = _pick_visual(kind, anchor["gender"], rng)
    if not visual:
        raise RuntimeError(
            "No hay videos de presentador. Copia intros, hombre y mujer en assets_video/templates/."
        )
    output = os.path.join(workdir, f"{kind}_{index}.ts")
    bgm = get_random_bgm(anchor["bgm_mood"], rng)
    sfx = get_random_sfx(anchor["sfx_type"], rng)
    ok = render_voice_bed(visual, audio, bgm, sfx, output, still_image=still)
    if not ok:
        raise RuntimeError(f"FFmpeg no armó el puente {kind}.")
    return output


def _webhook(endpoint, payload):
    url = f"{MAIN_API_URL}/api/lives/{endpoint}"
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"x-api-key": ADMIN_API_KEY},
            timeout=15,
        )
        if response.status_code >= 300:
            logger.warning("  [Webhook] %s respondió %s", endpoint, response.status_code)
        else:
            logger.info("  [Webhook] %s avisado.", endpoint)
    except Exception as exc:
        logger.warning("  [Webhook] No avisé a lfaftechapi (%s): %s", endpoint, exc)


def _schedule_ads(session, cue_offsets, stop_event, origin):
    last_fired = -10_000
    for offset in cue_offsets:
        while not stop_event.is_set():
            elapsed = time.monotonic() - origin
            wait = offset - elapsed
            if wait <= 0:
                break
            time.sleep(min(wait, 1.0))
        if stop_event.is_set():
            return
        if offset - last_fired < AD_MIN_GAP_SECONDS:
            logger.info("  [Pauta] Salteo corte en %.0fs (muy cerca del anterior).", offset)
            continue
        if session.insert_ad_cuepoint(AD_CUEPOINT_SECONDS):
            last_fired = offset


def _start_rtmp(playlist, rtmp_url):
    global _ffmpeg_proc
    cmd = [
        "ffmpeg", "-re", "-f", "concat", "-safe", "0", "-i", playlist,
        "-c", "copy",
        "-flvflags", "no_duration_filesize",
        "-f", "flv",
        rtmp_url,
    ]
    logger.info("  [Directo] Empieza la transmisión RTMP.")
    _ffmpeg_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return _ffmpeg_proc


def _wait_until_live(session, proc, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            err = b""
            try:
                err = proc.stderr.read() or b""
            except Exception:
                pass
            raise RuntimeError("FFmpeg cortó antes de salir al aire: " + err.decode("utf-8", errors="ignore")[-500:])
        status = ""
        try:
            status = session.stream_status()
        except Exception as exc:
            logger.warning("  [YouTube] No leí el estado del stream: %s", exc)
        if status == "active":
            session.go_live()
            return True
        time.sleep(3)
    logger.warning("  [YouTube] El stream no confirmó active a tiempo. Intento forzar el vivo.")
    return session.go_live()


def run_live(payload, rng):
    global _ffmpeg_proc
    _stop_event.clear()
    show = prepare_show(payload, rng, with_script=False)
    live_id = show["live_id"]
    if _already_done(live_id) and not payload.get("force"):
        logger.info("  [Directo] %s ya se emitió. No lo repito.", live_id)
        return {"status": "completed", "live_id": live_id, "message": "Ese directo ya salió al aire."}

    _set_state(
        status="preparing",
        live_id=live_id,
        pais=show["meta"]["pais_codigo"],
        canal=show["meta"]["canal"],
        cuenta=show.get("cuenta"),
        title=None,
        youtube_id=None,
        watch_url=None,
        monetization_enabled=False,
        error=None,
        video_count=show["rundown"]["video_count"],
        started_at=datetime.now().isoformat(timespec="seconds"),
    )

    workdir = os.path.join(TEMP_VIDEO_DIR, live_id)
    os.makedirs(workdir, exist_ok=True)
    session = None
    went_live = False

    try:
        logger.info("========== DIRECTO %s | %s ==========", live_id, show["meta"]["pais_nombre"])
        downloaded = _download_blocks(show["rundown"]["blocks"], workdir)
        if not downloaded:
            raise RuntimeError("No se pudo descargar ninguna nota.")

        # Se conserva el orden de bloques que mandó lfaftechapi.
        # Solo se sacan las notas que no se pudieron bajar.
        rundown = build_rundown([], explicit_blocks=downloaded)
        show["rundown"] = rundown
        show["meta"]["video_count"] = rundown["video_count"]
        anchor = show["anchor"]
        show["package"] = compose(show["meta"], rundown["blocks"], anchor, rng)
        show["package"]["anchor"] = anchor
        _set_state(title=show["package"]["youtube_title"], video_count=rundown["video_count"])

        segments = _build_segments(show, rng, workdir)
        playlist = write_concat_playlist([seg["path"] for seg in segments], os.path.join(workdir, "playlist.txt"))
        total = sum(seg["duration"] for seg in segments)
        logger.info("  [Directo] Escaleta lista: %s segmentos, %.0f segundos.", len(segments), total)

        thumb = os.path.join(workdir, "thumb.jpg")
        make_thumbnail(
            show["meta"]["pais_nombre"],
            show["meta"]["fecha_corta"] + "  |  " + show["meta"]["canal"],
            thumb,
            FONT_PATH,
        )

        session = YouTubeLiveSession().open(
            title=show["package"]["youtube_title"],
            description=show["package"]["youtube_description"],
            privacy=show["privacy"] or "public",
            account_index=show.get("cuenta"),
        )
        session.set_thumbnail(thumb)
        try:
            session.youtube.videos().update(
                part="snippet",
                body={
                    "id": session.broadcast_id,
                    "snippet": {
                        "title": show["package"]["youtube_title"][:100],
                        "description": show["package"]["youtube_description"][:5000],
                        "tags": show["package"]["youtube_tags"][:12],
                        "categoryId": "25",
                    },
                },
            ).execute()
        except Exception as exc:
            logger.warning("  [YouTube] No actualicé tags/categoría: %s", exc)

        proc = _start_rtmp(playlist, session.rtmp_url)
        origin = time.monotonic()
        live_ok = _wait_until_live(session, proc)
        went_live = live_ok or session.broadcast_status() == "live"
        if not went_live:
            raise RuntimeError("YouTube no pasó el directo a vivo.")

        _set_state(
            status="live",
            youtube_id=session.broadcast_id,
            watch_url=session.watch_url,
            monetization_enabled=session.monetization_enabled,
        )
        _mark_done(live_id, session.broadcast_id)
        _webhook("live_started", _event_payload(show, session, "live"))

        offsets = [seg["starts_at"] for seg in segments if seg.get("ad_break")]
        ad_thread = threading.Thread(
            target=_schedule_ads,
            args=(session, offsets, _stop_event, origin),
            daemon=True,
        )
        ad_thread.start()

        while proc.poll() is None:
            if _stop_event.is_set():
                proc.terminate()
                break
            time.sleep(2)
        ad_thread.join(timeout=2)

        if proc.returncode not in (0, None) and not _stop_event.is_set():
            err = b""
            try:
                err = proc.stderr.read() or b""
            except Exception:
                pass
            logger.error("  [Directo] FFmpeg terminó con error: %s", err.decode("utf-8", errors="ignore")[-500:])

        session.complete()
        _set_state(status="complete", monetization_enabled=session.monetization_enabled)
        _webhook("live_complete", _event_payload(show, session, "complete"))
        logger.info("========== DIRECTO TERMINADO %s ==========", session.watch_url)
        return {
            "status": "complete",
            "live_id": live_id,
            "youtube_id": session.broadcast_id,
            "watch_url": session.watch_url,
            "monetization_enabled": session.monetization_enabled,
            "title": show["package"]["youtube_title"],
        }
    except Exception as exc:
        logger.exception("  [Directo] Falló: %s", exc)
        _set_state(status="failed", error=str(exc))
        if session and went_live:
            session.complete()
        elif session:
            session.abandon()
        cuenta_aviso = show.get("cuenta")
        if session is not None and session.account_index is not None:
            cuenta_aviso = session.account_index
        _webhook("live_failed", _evento_fallo(show, live_id, cuenta_aviso, exc))
        return {"status": "failed", "live_id": live_id, "error": str(exc)}
    finally:
        _ffmpeg_proc = None
        _cleanup_dir(workdir)


def _evento_fallo(show, live_id, cuenta, exc):
    """Mismo aviso que el de salida, para que lfaftechapi cierre el job."""
    cuerpo = {
        "liveId": live_id,
        "pais": show["meta"]["pais_codigo"],
        "paisNombre": show["meta"]["pais_nombre"],
        "canal": show["meta"]["canal"],
        "cuenta": cuenta,
        "error": str(exc),
        "status": "failed",
        "videoCount": show["rundown"]["video_count"],
        "articleIds": [
            video["article_id"]
            for block in show["rundown"]["blocks"]
            for video in block["videos"]
        ],
    }
    package = show.get("package") or {}
    if package.get("youtube_title"):
        cuerpo["title"] = package["youtube_title"]
    anchor = package.get("anchor") or {}
    if anchor.get("name"):
        cuerpo["presenter"] = anchor["name"]
    if anchor.get("voice_key"):
        cuerpo["voice"] = anchor["voice_key"]
    return cuerpo


def _event_payload(show, session, status):
    return {
        "liveId": show["live_id"],
        "pais": show["meta"]["pais_codigo"],
        "paisNombre": show["meta"]["pais_nombre"],
        "youtubeId": session.broadcast_id,
        "watchUrl": session.watch_url,
        "title": show["package"]["youtube_title"],
        "description": show["package"]["youtube_description"],
        "monetizationEnabled": bool(session.monetization_enabled),
        "videoCount": show["rundown"]["video_count"],
        "voice": show["package"]["anchor"]["voice_key"],
        "presenter": show["package"]["anchor"]["name"],
        "scriptSource": show["package"]["source"],
        "status": status,
        "cuenta": session.account_index,
        "canal": show["meta"]["canal"],
        "articleIds": [
            video["article_id"]
            for block in show["rundown"]["blocks"]
            for video in block["videos"]
        ],
    }


def _ruta_local(url):
    """Acepta un mp4 que ya está en la computadora, además de http(s)."""
    text = str(url or "").strip()
    if not text or "://" in text and not text.lower().startswith("file:"):
        return None
    if text.lower().startswith("file:"):
        parsed = urlparse(text)
        text = unquote(parsed.path or "")
        if os.name == "nt" and text.startswith("/") and len(text) > 2 and text[2] == ":":
            text = text[1:]
    if os.path.isfile(text):
        return text
    return None


def _traer_nota(url, dest):
    local = _ruta_local(url)
    if local:
        logger.info("  [Media] Uso el archivo local %s", os.path.basename(local))
        shutil.copyfile(local, dest)
        if os.path.getsize(dest) > 1024:
            return dest
        return None
    return download_media(url, dest)


def _download_blocks(blocks, workdir):
    ready = []
    for block in blocks:
        kept = []
        for video in block["videos"]:
            ext = ".mp4"
            dest = os.path.join(workdir, f"nota_{uuid.uuid4().hex[:8]}{ext}")
            path = _traer_nota(video["video_url"], dest)
            if not path:
                logger.error("  [Directo] Salteo nota sin archivo: %s", video["titulo"])
                continue
            video = dict(video)
            video["local_path"] = path
            kept.append(video)
        if kept:
            ready.append({
                "categoria": block["categoria"],
                "label": block["label"],
                "videos": kept,
                "continuacion": block.get("continuacion", False),
            })
    return ready


def _build_segments(show, rng, workdir):
    anchor = show["package"]["anchor"]
    blocks = show["rundown"]["blocks"]
    segments = []
    clock = 0.0

    intro = _render_spoken("intro", show["package"]["intro_text"], anchor, rng, workdir, 0)
    intro_dur = probe_duration(intro)
    segments.append({
        "kind": "intro",
        "path": intro,
        "duration": intro_dur,
        "starts_at": 0,
        "ad_break": False,
        "titulo": "Apertura",
        "categoria": "apertura",
    })
    clock += intro_dur

    bridge_i = 0
    for index, block in enumerate(blocks):
        if index > 0:
            bridges = show["package"]["bridges"]
            if bridge_i < len(bridges):
                text = bridges[bridge_i]
            else:
                text = f"Ahora pasamos a {block['label']}."
            bridge_i += 1
            path = _render_spoken("puente", text, anchor, rng, workdir, index)
            duration = probe_duration(path)
            segments.append({
                "kind": "bridge",
                "path": path,
                "duration": duration,
                "starts_at": clock,
                "ad_break": True,
                "titulo": block["label"].capitalize(),
                "categoria": block["label"],
            })
            clock += duration
        for video in block["videos"]:
            norm = os.path.join(workdir, f"norm_{uuid.uuid4().hex[:8]}.ts")
            if not normalize_clip(video["local_path"], norm):
                logger.error("  [Directo] No normalicé %s", video["titulo"])
                continue
            duration = probe_duration(norm)
            segments.append({
                "kind": "news",
                "path": norm,
                "duration": duration,
                "starts_at": clock,
                "ad_break": False,
                "titulo": video["titulo"],
                "categoria": block["label"],
            })
            clock += duration

    outro = _render_spoken("outro", show["package"]["outro_text"], anchor, rng, workdir, 0)
    segments.append({
        "kind": "outro",
        "path": outro,
        "duration": probe_duration(outro),
        "starts_at": clock,
        "ad_break": False,
        "titulo": "Cierre",
        "categoria": "cierre",
    })
    return [seg for seg in segments if seg["duration"] > 0.4]


def _remux_mp4(playlist, destino):
    """Pasa la escaleta (mpegts) a un mp4 que el navegador puede reproducir."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", playlist,
        "-c", "copy", "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        destino,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=600)
    except subprocess.CalledProcessError as exc:
        detalle = (exc.stderr or b"").decode("utf-8", errors="ignore")[-400:]
        raise RuntimeError(f"No pude unir las notas en un solo video: {detalle}") from exc
    if not os.path.exists(destino) or probe_duration(destino) < 1:
        raise RuntimeError("El directo local quedó sin video.")
    return destino


def _borrar_menos(workdir, conservar):
    if not workdir or not os.path.isdir(workdir):
        return
    for name in os.listdir(workdir):
        if name in conservar:
            continue
        path = os.path.join(workdir, name)
        try:
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def armar_emision(show, rng, workdir):
    """
    El mismo armado que el directo de YouTube: baja cada nota, mezcla la voz
    del presentador y une todo. No abre YouTube ni avisa a lfaftechapi.
    Al terminar borra las descargas y deja solo el programa.
    """
    from config import TEMP_AUDIO_DIR

    os.makedirs(workdir, exist_ok=True)
    marca = time.time()
    downloaded = _download_blocks(show["rundown"]["blocks"], workdir)
    if not downloaded:
        raise RuntimeError(
            "No pude bajar ninguna nota. Cada video_url tiene que ser un mp4 que se pueda abrir."
        )

    rundown = build_rundown([], explicit_blocks=downloaded)
    show["rundown"] = rundown
    show["meta"]["video_count"] = rundown["video_count"]
    anchor = show["anchor"]
    show["package"] = compose(show["meta"], rundown["blocks"], anchor, rng)
    show["package"]["anchor"] = anchor

    segments = _build_segments(show, rng, workdir)
    if not any(seg["kind"] == "news" for seg in segments):
        raise RuntimeError("Las notas se bajaron, pero no quedaron listas para reproducir.")

    playlist = write_concat_playlist(
        [seg["path"] for seg in segments],
        os.path.join(workdir, "playlist.txt"),
    )
    programa = os.path.join(workdir, "programa.mp4")
    _remux_mp4(playlist, programa)
    _borrar_menos(workdir, {"programa.mp4"})
    if os.path.isdir(TEMP_AUDIO_DIR):
        for name in os.listdir(TEMP_AUDIO_DIR):
            path = os.path.join(TEMP_AUDIO_DIR, name)
            if not name.endswith(".mp3") or not os.path.isfile(path):
                continue
            try:
                if os.path.getmtime(path) >= marca - 1:
                    os.remove(path)
            except OSError:
                pass
    logger.info(
        "  [Directo] Programa local listo: %s notas, %.0f segundos. Las descargas ya se borraron.",
        rundown["video_count"],
        sum(seg["duration"] for seg in segments),
    )
    return segments, programa


def _cleanup_dir(workdir):
    if not workdir or not os.path.isdir(workdir):
        return
    for name in os.listdir(workdir):
        path = os.path.join(workdir, name)
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
    try:
        os.rmdir(workdir)
    except OSError:
        pass
