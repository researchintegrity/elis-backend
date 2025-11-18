"""
Quota status helper functions for augmenting responses with user storage information
Provides reusable logic for adding quota/storage fields to API responses
"""

from typing import Dict, Any, List
from app.utils.file_storage import get_quota_status


def augment_with_quota(
    resource: Dict[str, Any],
    user_id: str,
    user_quota: int
) -> Dict[str, Any]:
    """
    Add storage quota information to a single resource.
    
    Args:
        resource: Single resource dictionary (image, document, etc.)
        user_id: User ID to get quota for
        user_quota: User's storage limit in bytes
        
    Returns:
        Resource dictionary with user_storage_used and user_storage_remaining added
    """
    quota_status = get_quota_status(user_id, user_quota)
    resource["user_storage_used"] = quota_status["used_bytes"]
    resource["user_storage_remaining"] = quota_status["remaining_bytes"]
    return resource


def augment_list_with_quota(
    resources: List[Dict[str, Any]],
    user_id: str,
    user_quota: int
) -> List[Dict[str, Any]]:
    """
    Add storage quota information to multiple resources.
    
    Queries quota once and applies to all resources (efficient).
    
    Args:
        resources: List of resource dictionaries
        user_id: User ID to get quota for
        user_quota: User's storage limit in bytes
        
    Returns:
        List of resource dictionaries with user_storage_used and user_storage_remaining added
    """
    quota_status = get_quota_status(user_id, user_quota)
    
    for resource in resources:
        resource["user_storage_used"] = quota_status["used_bytes"]
        resource["user_storage_remaining"] = quota_status["remaining_bytes"]
    
    return resources


def get_quota_fields(user_id: str, user_quota: int) -> Dict[str, int]:
    """
    Get quota fields as a dictionary for direct assignment.
    
    Useful when building responses or dictionaries that need quota info.
    
    Args:
        user_id: User ID to get quota for
        user_quota: User's storage limit in bytes
        
    Returns:
        Dictionary with keys: user_storage_used, user_storage_remaining
    """
    quota_status = get_quota_status(user_id, user_quota)
    
    return {
        "user_storage_used": quota_status["used_bytes"],
        "user_storage_remaining": quota_status["remaining_bytes"]
    }
