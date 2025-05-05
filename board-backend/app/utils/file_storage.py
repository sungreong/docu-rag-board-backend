import os
import boto3
from botocore.exceptions import ClientError
import logging
from app.config import settings

# MinIO/S3 클라이언트 설정
s3_client = boto3.client(
    "s3",
    endpoint_url=settings.MINIO_ENDPOINT,
    aws_access_key_id=settings.MINIO_ACCESS_KEY,
    aws_secret_access_key=settings.MINIO_SECRET_KEY,
    region_name=settings.MINIO_REGION,
    config=boto3.session.Config(signature_version="s3v4"),
)


# 파일 URL 생성 함수
def generate_presigned_url(object_key, expiration=3600):
    """
    S3/MinIO에 저장된 파일의 임시 URL을 생성합니다.

    Args:
        object_key (str): 파일 객체 키
        expiration (int): URL 만료 시간 (초)

    Returns:
        str: 임시 URL
    """
    try:
        url = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": settings.MINIO_BUCKET, "Key": object_key}, ExpiresIn=expiration
        )
        return url
    except ClientError as e:
        logging.error(f"URL 생성 오류: {e}")
        return None


# 문서 파일 삭제 함수
def delete_document_files(document_id):
    """
    MinIO/S3에서 문서와 관련된 모든 파일을 삭제합니다.

    Args:
        document_id (str): 삭제할 문서의 ID

    Returns:
        dict: 삭제 결과 정보
    """
    try:
        bucket_name = settings.MINIO_BUCKET
        prefix = f"documents/{document_id}/"

        # 문서 디렉토리 내의 모든 파일 목록 조회
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)

        # 삭제할 파일이 없는 경우
        if "Contents" not in response:
            return {"status": "info", "message": "No files found to delete"}

        # 삭제할 객체 목록 구성
        objects_to_delete = [{"Key": obj["Key"]} for obj in response["Contents"]]

        # 파일 삭제 실행
        s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects_to_delete})

        return {
            "status": "success",
            "deleted_count": len(objects_to_delete),
            "message": f"Deleted {len(objects_to_delete)} files for document {document_id}",
        }
    except Exception as e:
        logging.error(f"파일 삭제 오류 (문서 ID: {document_id}): {str(e)}")
        return {"status": "error", "message": str(e)}
