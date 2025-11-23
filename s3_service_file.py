# Updated s3_service.py with English comments
"""
S3 service
"""
import boto3
from botocore.exceptions import ClientError
from config import settings
import logging
from typing import Optional


logger = logging.getLogger(__name__)


class S3Service:
    """Service for working with Amazon S3 or compatible storage"""
    
    def __init__(self):
        """Initialize S3 client"""
        client_config = {
            'region_name': settings.S3_REGION,
        }
        
        # Add credentials if provided
        if settings.AWS_ACCESS_KEY_ID:
            client_config['aws_access_key_id'] = settings.AWS_ACCESS_KEY_ID
        
        if settings.AWS_SECRET_ACCESS_KEY:
            client_config['aws_secret_access_key'] = settings.AWS_SECRET_ACCESS_KEY
        
        # For LocalStack
        if settings.AWS_ENDPOINT_URL:
            client_config['endpoint_url'] = settings.AWS_ENDPOINT_URL
        
        self.s3_client = boto3.client('s3', **client_config)
        self.bucket = settings.S3_BUCKET
        
        logger.info(f"S3Service initialized for bucket: {self.bucket}")
        self._ensure_bucket_exists()
    
    def _ensure_bucket_exists(self):
        """Check bucket existence and create if needed"""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket)
            logger.info(f"Bucket {self.bucket} exists")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                try:
                    self.s3_client.create_bucket(
                        Bucket=self.bucket,
                        CreateBucketConfiguration={'LocationConstraint': settings.S3_REGION}
                        if settings.S3_REGION != 'us-east-1' else {}
                    )
                    logger.info(f"Created bucket: {self.bucket}")
                except ClientError as create_error:
                    logger.error(f"Failed to create bucket: {create_error}")
            else:
                logger.error(f"Error checking bucket: {e}")
    
    async def upload_artifact(self, key: str, data: bytes, metadata: dict = None) -> Optional[str]:
        """
        Upload artifact to S3
        
        Args:
            key: Object key in S3
            data: Data to upload
            metadata: Object metadata
            
        Returns:
            Uploaded object URL or None on error
        """
        try:
            put_object_args = {
                'Bucket': self.bucket,
                'Key': key,
                'Body': data
            }
            
            if metadata:
                put_object_args['Metadata'] = metadata
            
            self.s3_client.put_object(**put_object_args)
            
            url = f"s3://{self.bucket}/{key}"
            logger.info(f"Uploaded artifact to {url}")
            return url
            
        except ClientError as e:
            logger.error(f"Failed to upload artifact to {key}: {e}")
            return None
    
    async def download_artifact(self, key: str) -> Optional[bytes]:
        """
        Download artifact from S3
        
        Args:
            key: Object key in S3
            
        Returns:
            Object data or None on error
        """
        try:
            response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
            data = response['Body'].read()
            logger.info(f"Downloaded artifact from s3://{self.bucket}/{key}")
            return data
            
        except ClientError as e:
            logger.error(f"Failed to download artifact from {key}: {e}")
            return None
    
    async def delete_artifact(self, key: str) -> bool:
        """
        Delete artifact from S3
        
        Args:
            key: Object key in S3
            
        Returns:
            True if successfully deleted
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket, Key=key)
            logger.info(f"Deleted artifact s3://{self.bucket}/{key}")
            return True
            
        except ClientError as e:
            logger.error(f"Failed to delete artifact {key}: {e}")
            return False
    
    async def list_artifacts(self, prefix: str) -> list:
        """
        Get artifact list by prefix
        
        Args:
            prefix: Search prefix
            
        Returns:
            List of object keys
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix
            )
            
            if 'Contents' not in response:
                return []
            
            keys = [obj['Key'] for obj in response['Contents']]
            logger.info(f"Found {len(keys)} artifacts with prefix {prefix}")
            return keys
            
        except ClientError as e:
            logger.error(f"Failed to list artifacts with prefix {prefix}: {e}")
            return []
    
    def get_presigned_url(self, key: str, expiration: int = 3600) -> Optional[str]:
        """
        Generate presigned URL for download
        
        Args:
            key: Object key in S3
            expiration: URL expiration time in seconds
            
        Returns:
            Presigned URL or None on error
        """
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket, 'Key': key},
                ExpiresIn=expiration
            )
            logger.info(f"Generated presigned URL for {key}")
            return url
            
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL for {key}: {e}")
            return None