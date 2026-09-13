import datetime
from django.conf import settings
from minio import Minio
from minio.error import S3Error

def get_minio_client():
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_USE_SSL,
    )

def ensure_bucket_exists(client, bucket_name):
    if not client.bucket_exists(bucket_name):
        client.make_bucket(bucket_name)

def upload_document(file_obj, object_key, mime_type, size):
    client = get_minio_client()
    bucket = settings.MINIO_BUCKET_NAME
    ensure_bucket_exists(client, bucket)

    client.put_object(
        bucket,
        object_key,
        file_obj,
        length=size,
        content_type=mime_type,
    )

def get_document_url(object_key):
    client = get_minio_client()
    bucket = settings.MINIO_BUCKET_NAME

    # We must authorize downloads in the view and redirect or stream.
    # We generate a short-lived presigned URL.
    try:
        url = client.get_presigned_url(
            "GET",
            bucket,
            object_key,
            expires=datetime.timedelta(minutes=5),
        )
        return url
    except S3Error:
        return None

def get_document_bytes(object_key):
    client = get_minio_client()
    bucket = settings.MINIO_BUCKET_NAME

    try:
        response = client.get_object(bucket, object_key)
        data = response.read()
        return data
    except S3Error:
        return None
    finally:
        try:
            response.close()
            response.release_conn()
        except Exception:
            pass

def delete_document(object_key):
    client = get_minio_client()
    bucket = settings.MINIO_BUCKET_NAME
    try:
        client.remove_object(bucket, object_key)
    except S3Error:
        pass
