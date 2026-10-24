"""Private interchangeable media storage. No public or signed URLs in v1."""
from pathlib import PurePosixPath
import re
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files import File
from django.core.files.storage import FileSystemStorage, Storage
from django.utils.deconstruct import deconstructible


def safe_filename(value, fallback='archivo'):
    value = PurePosixPath(str(value or '').replace('\\', '/')).name
    value = ''.join(char for char in value if ord(char) >= 32 and ord(char) != 127)
    return value[:200].strip(' .') or fallback


def validate_key(name):
    if not re.fullmatch(r'inbox-media/\d+/[0-9a-f]{32}/[0-9a-f]{32}\.bin', str(name)):
        raise SuspiciousFileOperation('Invalid private media key')
    return name


class PrivateLocalStorage(FileSystemStorage):
    def url(self, name):
        raise NotImplementedError('Media requires the authenticated Inbox endpoint')


class B2MediaStorage(Storage):
    def get_available_name(self, name, max_length=None):
        return validate_key(name)

    def __init__(self):
        import boto3
        from botocore.config import Config

        endpoint = settings.MEDIA_B2_ENDPOINT_URL
        parsed = urlparse(endpoint)
        if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
                or not re.fullmatch(r's3\.[a-z0-9-]+\.backblazeb2\.com', parsed.hostname or '')
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ImproperlyConfigured('Dedicated B2 media endpoint is required')
        self.bucket = settings.MEDIA_B2_BUCKET
        if not self.bucket or not settings.MEDIA_B2_ACCESS_KEY_ID or not settings.MEDIA_B2_SECRET_ACCESS_KEY:
            raise ImproperlyConfigured('Dedicated B2 media bucket/key is required')
        self.client = boto3.client('s3', endpoint_url=endpoint,
            region_name=settings.MEDIA_B2_REGION_NAME,
            aws_access_key_id=settings.MEDIA_B2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.MEDIA_B2_SECRET_ACCESS_KEY,
            config=Config(signature_version='s3v4', connect_timeout=5, read_timeout=30,
                retries={'total_max_attempts': 1}, s3={'addressing_style': 'path'},
                request_checksum_calculation='when_required', response_checksum_validation='when_required'))

    def _open(self, name, mode='rb'):
        from botocore.exceptions import ClientError
        validate_key(name)
        if mode not in ('r', 'rb'):
            raise ValueError('Media storage is read-only through open')
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=name)
        except ClientError as error:
            if str(error.response.get('Error', {}).get('Code')) in ('404', 'NoSuchKey', 'NotFound'):
                raise FileNotFoundError('Media object missing') from None
            raise
        return File(response['Body'], name=name)

    def _save(self, name, content):
        validate_key(name)
        content.seek(0)
        self.client.put_object(Bucket=self.bucket, Key=name, Body=content,
            ContentType=getattr(content, 'content_type', 'application/octet-stream'), ServerSideEncryption='AES256')
        return name

    def exists(self, name):
        from botocore.exceptions import ClientError
        validate_key(name)
        try:
            self.client.head_object(Bucket=self.bucket, Key=name)
            return True
        except ClientError as error:
            if str(error.response.get('Error', {}).get('Code')) in ('404', 'NoSuchKey', 'NotFound'):
                return False
            raise

    def delete(self, name):
        # B2 buckets are versioned. Delete every matching version AND marker,
        # never only hide the current object. Prefix matches are checked exactly.
        validate_key(name)
        paginator = self.client.get_paginator('list_object_versions')
        versions = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=name):
            versions.extend(dict(Key=item['Key'], VersionId=item['VersionId'])
                for item in [*page.get('Versions', []), *page.get('DeleteMarkers', [])] if item['Key'] == name)
        # Finish pagination before deleting: version markers remain stable.
        for start in range(0, len(versions), 1000):
            result = self.client.delete_objects(Bucket=self.bucket, Delete={'Objects': versions[start:start + 1000], 'Quiet': True})
            if result.get('Errors'):
                raise OSError('Media version purge failed')
        # A successful DELETE response is not proof of absence. Re-list ALL
        # versions/markers; a partial failure or concurrent writer stays pending.
        for page in paginator.paginate(Bucket=self.bucket, Prefix=name):
            if any(item['Key'] == name for item in [*page.get('Versions', []), *page.get('DeleteMarkers', [])]):
                raise OSError('Media purge verification failed')

    def url(self, name):
        raise NotImplementedError('Media requires the authenticated Inbox endpoint')


@deconstructible
class InboxMediaStorage(Storage):
    """Resolve settings lazily: migrations/imports never contact B2."""
    def generate_filename(self, filename):
        # FileField delegates here; base Storage uses OS path normalization,
        # which changes separators on Windows. Object keys are always POSIX.
        return validate_key(str(filename).replace('\\', '/'))

    def _backend(self):
        if settings.MEDIA_BACKEND == 'local':
            if not settings.INBOX_MEDIA_ALLOW_LOCAL:
                raise ImproperlyConfigured('Local media is restricted to development/tests')
            return PrivateLocalStorage(location=settings.INBOX_MEDIA_ROOT,
                file_permissions_mode=0o600, directory_permissions_mode=0o700, allow_overwrite=True)
        if settings.MEDIA_BACKEND != 'b2':
            raise ImproperlyConfigured('Unknown media backend')
        if not settings.INBOX_MEDIA_PRODUCTION_APPROVED:
            raise ImproperlyConfigured('Media production gates have not been approved')
        return B2MediaStorage()

    def _open(self, name, mode='rb'):
        validate_key(name)
        return self._backend().open(name, mode)

    def _save(self, name, content):
        validate_key(name)
        return self._backend().save(name, content)

    def get_available_name(self, name, max_length=None):
        return validate_key(name)  # UUID claim keys are never shared by writers.

    def exists(self, name):
        validate_key(name)
        return self._backend().exists(name)

    def delete(self, name):
        validate_key(name)
        return self._backend().delete(name)

    def url(self, name):
        raise NotImplementedError('Media requires the authenticated Inbox endpoint')


def media_storage():
    return InboxMediaStorage()


def media_upload_path(instance, filename):
    from uuid import uuid4
    return f'inbox-media/{instance.organization_id}/{instance.public_id.hex}/{uuid4().hex}.bin'
