# -*- coding: utf-8 -*-
"""Subida opcional a Cloudflare R2. Mismo contrato que TTS-FMPEG. Si no hay claves, no hace nada."""

import datetime
import logging
import os

import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
SECRET_KEY = os.getenv("R2_SECRET_KEY")
BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
PUBLIC_DOMAIN = os.getenv("R2_PUBLIC_DOMAIN")


def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )


def upload_media_to_r2(file_path, file_name):
    if not os.path.exists(file_path):
        logger.error("  [R2] No existe %s", file_path)
        return None
    if not all([ACCOUNT_ID, ACCESS_KEY, SECRET_KEY, BUCKET_NAME, PUBLIC_DOMAIN]):
        logger.info("  [R2] Sin credenciales. No subo %s.", file_name)
        return None
    try:
        tipo = "application/octet-stream"
        if file_name.lower().endswith(".mp3"):
            tipo = "audio/mpeg"
        elif file_name.lower().endswith(".mp4"):
            tipo = "video/mp4"
        elif file_name.lower().endswith(".jpg") or file_name.lower().endswith(".jpeg"):
            tipo = "image/jpeg"
        _client().upload_file(
            Filename=file_path,
            Bucket=BUCKET_NAME,
            Key=file_name,
            ExtraArgs={"ContentType": tipo, "CacheControl": "max-age=31536000"},
        )
        url = f"{PUBLIC_DOMAIN.rstrip('/')}/{file_name}"
        logger.info("  [R2] Subido %s", url)
        return url
    except Exception as exc:
        logger.error("  [R2] Error: %s", exc)
        return None


def delete_old_files_from_r2(days_old=28):
    if not all([ACCOUNT_ID, ACCESS_KEY, SECRET_KEY, BUCKET_NAME]):
        return False
    try:
        s3 = _client()
        limite = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_old)
        response = s3.list_objects_v2(Bucket=BUCKET_NAME)
        for obj in response.get("Contents", []):
            if obj["LastModified"] < limite:
                s3.delete_object(Bucket=BUCKET_NAME, Key=obj["Key"])
        return True
    except Exception as exc:
        logger.error("  [R2] Limpieza falló: %s", exc)
        return False
