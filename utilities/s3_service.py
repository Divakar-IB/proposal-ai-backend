import os
import tempfile
from typing import Optional

import boto3
from io import BytesIO
from botocore.exceptions import ClientError
from pathlib import Path
from uuid import uuid4
from config import config

class S3Client:

    _client = None

    @classmethod
    def get_client(cls):
        if cls._client is None:
            cls._client = boto3.client(
                "s3",
                aws_access_key_id=config.aws.access_key_id,
                aws_secret_access_key=config.aws.secret_access_key,
                region_name=config.aws.region,
            )

        return cls._client

# print("Bucket:", config.aws.bucket_name)
# print("Region:", config.aws.region)
# print("Access Key:", config.aws.access_key_id)
class S3PathBuilder:
    @staticmethod
    def knowledge_document(
        user_id: int,
        category_id: int,
        filename: str,
        document_id: Optional[int] = None,
    ) -> str:
        """
        document_id is optional: the S3 key must be built *before* the DB
        row exists (upload has to succeed first), so a fresh uuid is used
        as the folder segment when no document_id is available yet.
        """

        extension = Path(filename).suffix
        doc_segment = str(document_id) if document_id is not None else uuid4().hex

        return (
            f"input/knowledge/"
            f"{user_id}/"
            f"{category_id}/"
            f"{doc_segment}/"
            f"{uuid4()}{extension}"
        )

    @staticmethod
    def requirement_document(
        user_id: int,
        filename: str,
        requirement_document_id: Optional[int] = None,
    ) -> str:
        """
        requirement_document_id is optional: the S3 key must be built *before* the
        DB row exists (upload has to succeed first), so a fresh uuid is used as
        the folder segment when no requirement_document_id is available yet.
        """

        extension = Path(filename).suffix
        doc_segment = str(requirement_document_id) if requirement_document_id is not None else uuid4().hex

        return (
            f"input/requirements/"
            f"{user_id}/"
            f"{doc_segment}/"
            f"{uuid4()}{extension}"
        )

    @staticmethod
    def proposal_docx(
        user_id: int,
        proposal_id: int,
    ) -> str:

        return (
            f"output/proposals/"
            f"{user_id}/"
            f"{proposal_id}/"
            f"proposal.docx"
        )

    @staticmethod
    def proposal_pdf(
        user_id: int,
        proposal_id: int,
    ) -> str:

        return (
            f"output/proposals/"
            f"{user_id}/"
            f"{proposal_id}/"
            f"proposal.pdf"
        )

    @staticmethod
    def organization_logo(filename: str) -> str:
        """Singleton branding asset — no per-user/per-id segment needed,
        just a fresh uuid per upload so replacing the logo never collides
        with (or requires deleting before uploading over) the old key."""

        extension = Path(filename).suffix
        return f"input/organization/logo/{uuid4()}{extension}"

# S3 Service (create,view, update, delete)
class S3Service:

    def __init__(self):
        self.client = S3Client.get_client()
        self.bucket = config.aws.bucket_name

    # Upload
    def upload_file(self, file, file_path: str):

        self.client.upload_fileobj(
            Fileobj=file.file,
            Bucket=self.bucket,
            Key=file_path,
            ExtraArgs={
                "ContentType": file.content_type
            }
        )

        return file_path

    def upload_bytes(
        self,
        data: bytes,
        file_path: str,
        content_type: str = "application/octet-stream",
    ):

        self.client.upload_fileobj(
            BytesIO(data),
            self.bucket,
            file_path,
            ExtraArgs={
                "ContentType": content_type
            }
        )

        return file_path

    
    # Download
    def download_file(self, file_path: str) -> bytes:

        response = self.client.get_object(
            Bucket=self.bucket,
            Key=file_path,
        )

        return response["Body"].read()

    def download_fileobj(self, file_path: str) -> BytesIO:
        """Downloads into an in-memory buffer, positioned at the start."""

        buffer = BytesIO()
        self.client.download_fileobj(self.bucket, file_path, buffer)
        buffer.seek(0)

        return buffer

    def download_to_tempfile(self, file_path: str, suffix: str = "") -> str:
        """
        Downloads to a local temp file and returns its path.
        Callers (e.g. the processing pipeline) own cleanup of the returned path.
        """

        fd, local_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        self.client.download_file(self.bucket, file_path, local_path)

        return local_path

    # Delete
    def delete_file(self, file_path: str):

        self.client.delete_object(
            Bucket=self.bucket,
            Key=file_path,
        )

    # Exists
    def file_exists(self, file_path: str):

        try:

            self.client.head_object(
                Bucket=self.bucket,
                Key=file_path,
            )

            return True

        except ClientError:

            return False

    # Copy
    def copy_file(
        self,
        source_path: str,
        destination_path: str,
    ):

        self.client.copy_object(
            Bucket=self.bucket,
            CopySource={
                "Bucket": self.bucket,
                "Key": source_path,
            },
            Key=destination_path,
        )

        return destination_path

    # Move
    def move_file(
        self,
        source_path: str,
        destination_path: str,
    ):

        self.copy_file(
            source_path,
            destination_path,
        )

        self.delete_file(source_path)

        return destination_path

    # Rename
    def rename_file(
        self,
        old_path: str,
        new_path: str,
    ):

        return self.move_file(
            old_path,
            new_path,
        )

    # Metadata
    def get_metadata(
        self,
        file_path: str,
    ):

        return self.client.head_object(
            Bucket=self.bucket,
            Key=file_path,
        )

    # Presigned URL
    def generate_presigned_url(
        self,
        file_path: str,
        expires_in: int = 3600,
    ):

        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": file_path,
            },
            ExpiresIn=expires_in,
        )

    # List Files
    def list_files(
        self,
        prefix: str,
    ):

        response = self.client.list_objects_v2(
            Bucket=self.bucket,
            Prefix=prefix,
        )

        if "Contents" not in response:
            return []

        return [
            obj["Key"]
            for obj in response["Contents"]
        ]

    # Delete Folder
    def delete_folder(
        self,
        prefix: str,
    ):

        files = self.list_files(prefix)

        if not files:
            return 0

        self.client.delete_objects(
            Bucket=self.bucket,
            Delete={
                "Objects": [
                    {"Key": key}
                    for key in files
                ]
            }
        )

        return len(files)