# -*- coding: utf-8 -*-
"""
Abre el directo en YouTube, lo deja público y activa la pauta (mid-rolls).

La monetización real solo prende si el canal está en el Programa de Partners
y el token se generó con los scopes de directo (ver generar_token.py).
Si YouTube rechaza la pauta, el vivo sale igual y queda asentado en el log.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from config import AD_REPEAT_SECONDS, LOCKS_DIR, MAX_ACCOUNTS, SCOPES

logger = logging.getLogger(__name__)


class YouTubeLiveError(RuntimeError):
    pass


def _mask(secret):
    if not secret:
        return ""
    if len(secret) < 8:
        return "****"
    return secret[:3] + "…" + secret[-2:]


def _rotator_path():
    os.makedirs(LOCKS_DIR, exist_ok=True)
    return os.path.join(LOCKS_DIR, "live_account_rotator.txt")


def next_account_index():
    path = _rotator_path()
    current = 0
    if os.path.exists(path):
        try:
            raw = open(path, "r", encoding="utf-8").read().strip()
            if raw.isdigit():
                current = int(raw)
        except OSError:
            current = 0
    nxt = (current + 1) % MAX_ACCOUNTS
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(nxt))
    except OSError as exc:
        logger.warning("  [YouTube] No pude guardar la rotación: %s", exc)
    return nxt


def get_authenticated_service(account_index):
    token_file = os.path.join(os.getcwd(), f"token_{account_index}.json")
    if not os.path.exists(token_file):
        logger.warning("  [YouTube] Falta %s", token_file)
        return None
    try:
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    except Exception as exc:
        logger.error("  [YouTube] Token %s ilegible: %s", account_index, exc)
        return None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_file, "w", encoding="utf-8") as handle:
                    handle.write(creds.to_json())
            except Exception as exc:
                logger.error("  [YouTube] No refresqué el token %s: %s", account_index, exc)
                return None
        else:
            logger.error("  [YouTube] El token %s hay que regenerarlo con generar_token.py", account_index)
            return None
    try:
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:
        logger.error("  [YouTube] No armé el cliente: %s", exc)
        return None


def _is_quota(error):
    body = ""
    try:
        body = error.content.decode("utf-8", errors="ignore")
    except Exception:
        body = str(error)
    return error.resp.status in (403, 429) and ("quotaExceeded" in body or "rateLimitExceeded" in body)


def _broadcast_body(title, description, privacy, with_monetization):
    start = datetime.now(timezone.utc) + timedelta(seconds=20)
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "scheduledStartTime": start.isoformat().replace("+00:00", "Z"),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
        "contentDetails": {
            "enableAutoStart": True,
            "enableAutoStop": True,
            "enableDvr": True,
            "recordFromStart": True,
            "enableEmbed": True,
            "startWithSlate": False,
            "latencyPreference": "normal",
            "monitorStream": {
                "enableMonitorStream": False,
                "broadcastStreamDelayMs": 0,
            },
        },
    }
    if with_monetization:
        body["monetizationDetails"] = {
            "cuepointSchedule": {
                "enabled": True,
                "repeatIntervalSecs": str(AD_REPEAT_SECONDS),
                "scheduleStrategy": "nonConcurrent",
            }
        }
    return body


class YouTubeLiveSession:
    def __init__(self):
        self.youtube = None
        self.account_index = None
        self.broadcast_id = None
        self.stream_id = None
        self.rtmp_url = None
        self.monetization_enabled = False
        self.watch_url = None
        self.privacy = "public"

    def open(self, title, description, privacy="public"):
        self.privacy = privacy if privacy in ("public", "unlisted", "private") else "public"
        start = next_account_index()
        last_error = None

        for offset in range(MAX_ACCOUNTS):
            account = (start + offset) % MAX_ACCOUNTS
            youtube = get_authenticated_service(account)
            if not youtube:
                continue
            try:
                self.youtube = youtube
                self.account_index = account
                self._create_stream(title)
                self._create_broadcast(title, description, with_monetization=True)
                self._bind()
                self.watch_url = f"https://www.youtube.com/watch?v={self.broadcast_id}"
                logger.info(
                    "  [YouTube] Directo creado en cuenta %s: %s (pauta=%s)",
                    account, self.watch_url, self.monetization_enabled,
                )
                return self
            except HttpError as exc:
                last_error = exc
                if _is_quota(exc):
                    logger.warning("  [YouTube] Cuota llena en cuenta %s. Siguiente.", account)
                    self._cleanup_partial()
                    continue
                logger.error("  [YouTube] Error en cuenta %s: %s", account, exc)
                self._cleanup_partial()
            except Exception as exc:
                last_error = exc
                logger.error("  [YouTube] Fallo inesperado en cuenta %s: %s", account, exc)
                self._cleanup_partial()

        raise YouTubeLiveError(f"Ninguna cuenta pudo abrir el directo. Último error: {last_error}")

    def _create_stream(self, title):
        stream = self.youtube.liveStreams().insert(
            part="snippet,cdn,contentDetails,status",
            body={
                "snippet": {"title": title[:100]},
                "cdn": {
                    "frameRate": "30fps",
                    "ingestionType": "rtmp",
                    "resolution": "720p",
                },
                "contentDetails": {"isReusable": False},
            },
        ).execute()
        self.stream_id = stream["id"]
        ingestion = stream["cdn"]["ingestionInfo"]
        address = ingestion["ingestionAddress"].rstrip("/")
        key = ingestion["streamName"]
        self.rtmp_url = f"{address}/{key}"
        logger.info("  [YouTube] Ingesta lista. Clave %s", _mask(key))

    def _create_broadcast(self, title, description, with_monetization):
        parts = "snippet,status,contentDetails"
        if with_monetization:
            parts += ",monetizationDetails"
        try:
            broadcast = self.youtube.liveBroadcasts().insert(
                part=parts,
                body=_broadcast_body(title, description, self.privacy, with_monetization),
            ).execute()
            self.broadcast_id = broadcast["id"]
            self.monetization_enabled = with_monetization
        except HttpError as exc:
            body = exc.content.decode("utf-8", errors="ignore") if exc.content else str(exc)
            if with_monetization and exc.resp.status in (400, 403):
                logger.warning(
                    "  [YouTube] No aceptó la pauta automática (%s). "
                    "El directo se crea igual. Revisa que el canal esté en el Programa de Partners "
                    "y que la monetización de vivos esté habilitada en YouTube Studio.",
                    body[:300],
                )
                self._create_broadcast(title, description, with_monetization=False)
                return
            raise

    def _bind(self):
        self.youtube.liveBroadcasts().bind(
            part="id,contentDetails",
            id=self.broadcast_id,
            streamId=self.stream_id,
        ).execute()

    def stream_status(self):
        if not self.youtube or not self.stream_id:
            return ""
        data = self.youtube.liveStreams().list(part="status", id=self.stream_id).execute()
        items = data.get("items") or []
        if not items:
            return ""
        return (items[0].get("status") or {}).get("streamStatus", "")

    def broadcast_status(self):
        if not self.youtube or not self.broadcast_id:
            return ""
        data = self.youtube.liveBroadcasts().list(
            part="status", id=self.broadcast_id
        ).execute()
        items = data.get("items") or []
        if not items:
            return ""
        return (items[0].get("status") or {}).get("lifeCycleStatus", "")

    def go_live(self):
        """Por si enableAutoStart no alcanzó a disparar solo."""
        status = self.broadcast_status()
        if status == "live":
            return True
        for target in ("testing", "live"):
            if status == "live":
                return True
            if target == "testing" and status not in ("ready", "testStarting", "created"):
                continue
            try:
                self.youtube.liveBroadcasts().transition(
                    broadcastStatus=target,
                    id=self.broadcast_id,
                    part="status",
                ).execute()
                status = target
            except HttpError as exc:
                logger.warning("  [YouTube] Transición a %s no aceptada: %s", target, exc)
        return self.broadcast_status() == "live"

    def insert_ad_cuepoint(self, duration_secs):
        if not self.youtube or not self.broadcast_id:
            return False
        try:
            self.youtube.liveBroadcasts().cuepoint(
                id=self.broadcast_id,
                body={
                    "id": self.broadcast_id,
                    "insertionOffsetTimeMs": 0,
                    "cueType": "cueTypeAd",
                    "durationSecs": int(duration_secs),
                },
            ).execute()
            self.monetization_enabled = True
            logger.info("  [YouTube] Cuepoint de anuncio insertado (%ss).", duration_secs)
            return True
        except HttpError as exc:
            body = exc.content.decode("utf-8", errors="ignore") if exc.content else str(exc)
            logger.warning("  [YouTube] Cuepoint rechazado: %s", body[:300])
            return False

    def set_thumbnail(self, path):
        if not path or not os.path.exists(path) or not self.broadcast_id:
            return False
        try:
            self.youtube.thumbnails().set(
                videoId=self.broadcast_id,
                media_body=MediaFileUpload(path),
            ).execute()
            logger.info("  [YouTube] Miniatura aplicada.")
            return True
        except Exception as exc:
            logger.warning("  [YouTube] Miniatura no aplicada: %s", exc)
            return False

    def complete(self):
        if not self.youtube or not self.broadcast_id:
            return
        try:
            status = self.broadcast_status()
            if status in ("complete", "revoked"):
                return
            self.youtube.liveBroadcasts().transition(
                broadcastStatus="complete",
                id=self.broadcast_id,
                part="status",
            ).execute()
            logger.info("  [YouTube] Directo cerrado.")
        except HttpError as exc:
            logger.warning("  [YouTube] No pude cerrar el directo: %s", exc)

    def _cleanup_partial(self):
        if self.youtube and self.broadcast_id:
            try:
                self.youtube.liveBroadcasts().delete(id=self.broadcast_id).execute()
            except Exception:
                pass
        if self.youtube and self.stream_id:
            try:
                self.youtube.liveStreams().delete(id=self.stream_id).execute()
            except Exception:
                pass
        self.broadcast_id = None
        self.stream_id = None
        self.rtmp_url = None
        self.youtube = None

    def abandon(self):
        """Borra el directo si nunca llegó a salir al aire."""
        self._cleanup_partial()
