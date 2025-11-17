"""
Pydantic schemas for request/response validation
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime
from typing import Optional
from bson import ObjectId
from app.config.settings import (
    USERNAME_MIN_LENGTH,
    USERNAME_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    FULL_NAME_MAX_LENGTH,
)


class UserLogin(BaseModel):
    """User login credentials"""
    username: str = Field(..., min_length=USERNAME_MIN_LENGTH, description="Username or email")
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, description="User password")

    class Config:
        schema_extra = {
            "example": {
                "username": "johndoe",
                "password": "securepassword123"
            }
        }


class UserRegister(BaseModel):
    """User registration data"""
    username: str = Field(..., min_length=USERNAME_MIN_LENGTH, max_length=USERNAME_MAX_LENGTH, description="Unique username")
    email: EmailStr = Field(..., description="Valid email address")
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, description=f"Password (min {PASSWORD_MIN_LENGTH} characters)")
    full_name: Optional[str] = Field(None, description="User's full name")

    class Config:
        schema_extra = {
            "example": {
                "username": "johndoe",
                "email": "john@example.com",
                "password": "securepassword123",
                "full_name": "John Doe"
            }
        }


class UserUpdate(BaseModel):
    """User profile update data"""
    full_name: Optional[str] = Field(None, max_length=FULL_NAME_MAX_LENGTH, description="User's full name")
    email: Optional[EmailStr] = Field(None, description="Valid email address")

    class Config:
        schema_extra = {
            "example": {
                "full_name": "John Doe Updated",
                "email": "newemail@example.com"
            }
        }


class UserResponse(BaseModel):
    """User response model"""
    id: str = Field(alias="_id")
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    storage_used_bytes: int = 0
    storage_limit_bytes: int = 1073741824  # 1 GB default
    created_at: datetime
    updated_at: datetime

    @field_validator('id', mode='before')
    @classmethod
    def convert_object_id(cls, v):
        """Convert MongoDB ObjectId to string"""
        if isinstance(v, ObjectId):
            return str(v)
        return v

    class Config:
        from_attributes = True
        schema_extra = {
            "example": {
                "_id": "507f1f77bcf86cd799439011",
                "username": "johndoe",
                "email": "john@example.com",
                "full_name": "John Doe",
                "is_active": True,
                "storage_used_bytes": 524288000,
                "storage_limit_bytes": 1073741824,
                "created_at": "2025-01-01T10:00:00",
                "updated_at": "2025-01-02T15:30:00"
            }
        }


class TokenResponse(BaseModel):
    """Authentication token response"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    expires_in: int

    class Config:
        schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "user": {
                    "_id": "507f1f77bcf86cd799439011",
                    "username": "johndoe",
                    "email": "john@example.com",
                    "full_name": "John Doe",
                    "is_active": True,
                    "created_at": "2025-01-01T10:00:00",
                    "updated_at": "2025-01-02T15:30:00"
                },
                "expires_in": 86400
            }
        }


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str

    class Config:
        schema_extra = {
            "example": {
                "message": "Operation completed successfully"
            }
        }


class ErrorResponse(BaseModel):
    """Error response model"""
    error: str
    status_code: int

    class Config:
        schema_extra = {
            "example": {
                "error": "Username or email already registered",
                "status_code": 400
            }
        }


class UserInDB(BaseModel):
    """User model stored in database"""
    username: str
    email: str
    hashed_password: str
    full_name: Optional[str] = None
    is_active: bool = True
    storage_used_bytes: int = 0  # Total storage used (PDFs + images)
    storage_limit_bytes: int = 1073741824  # 1 GB default
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# Document Upload Schemas
# ============================================================================

class DocumentCreate(BaseModel):
    """Document creation request (internal use)"""
    user_id: str
    filename: str
    file_path: str
    file_size: int

    class Config:
        schema_extra = {
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "filename": "research_paper.pdf",
                "file_path": "/workspace/507f1f77bcf86cd799439011/pdfs/1730000000_research_paper.pdf",
                "file_size": 2048576
            }
        }


class ExtractedImageInfo(BaseModel):
    """Information about an extracted image"""
    filename: str
    path: str
    size: int
    mime_type: str


class DocumentResponse(BaseModel):
    """Document response model"""
    id: str = Field(alias="_id")
    user_id: str
    filename: str
    file_path: str
    file_size: int
    extraction_status: str = Field(default="pending", description="pending|completed|failed")
    extracted_image_count: int = 0
    extraction_errors: list[str] = Field(default_factory=list)
    extracted_images: list[ExtractedImageInfo] = Field(default_factory=list)
    uploaded_date: datetime
    user_storage_used: int = 0  # Total bytes used by user
    user_storage_remaining: int = 1073741824  # Remaining quota

    @field_validator('id', mode='before')
    @classmethod
    def convert_object_id(cls, v):
        """Convert MongoDB ObjectId to string"""
        if isinstance(v, ObjectId):
            return str(v)
        return v

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "_id": "507f1f77bcf86cd799439012",
                "user_id": "507f1f77bcf86cd799439011",
                "filename": "research_paper.pdf",
                "file_path": "/workspace/507f1f77bcf86cd799439011/pdfs/1730000000_research_paper.pdf",
                "file_size": 2048576,
                "extraction_status": "completed",
                "extracted_image_count": 5,
                "extraction_errors": [],
                "uploaded_date": "2025-01-01T10:00:00",
                "user_storage_used": 524288000,
                "user_storage_remaining": 549453824
            }
        }


class DocumentInDB(BaseModel):
    """Document model stored in database"""
    user_id: str
    filename: str
    file_path: str
    file_size: int
    extraction_status: str = "pending"
    extracted_image_count: int = 0
    extraction_errors: list[str] = Field(default_factory=list)
    uploaded_date: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# Image Upload Schemas
# ============================================================================

class ImageCreate(BaseModel):
    """Image creation request (internal use)"""
    user_id: str
    filename: str
    file_path: str
    file_size: int
    source_type: str = Field(default="uploaded", description="extracted|uploaded")
    document_id: Optional[str] = Field(None, description="Reference to document if extracted")

    class Config:
        schema_extra = {
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "filename": "figure_1.png",
                "file_path": "/workspace/507f1f77bcf86cd799439011/images/extracted/507f1f77bcf86cd799439012/figure_1.png",
                "file_size": 512000,
                "source_type": "extracted",
                "document_id": "507f1f77bcf86cd799439012"
            }
        }


class ImageResponse(BaseModel):
    """Image response model"""
    id: str = Field(alias="_id")
    user_id: str
    filename: str
    file_path: str
    file_size: int
    source_type: str = Field(description="extracted|uploaded")
    document_id: Optional[str] = None
    uploaded_date: datetime
    user_storage_used: int = 0  # Total bytes used by user
    user_storage_remaining: int = 1073741824  # Remaining quota

    @field_validator('id', mode='before')
    @classmethod
    def convert_object_id(cls, v):
        """Convert MongoDB ObjectId to string"""
        if isinstance(v, ObjectId):
            return str(v)
        return v

    class Config:
        from_attributes = True
        schema_extra = {
            "example": {
                "_id": "507f1f77bcf86cd799439013",
                "user_id": "507f1f77bcf86cd799439011",
                "filename": "figure_1.png",
                "file_path": "/workspace/507f1f77bcf86cd799439011/images/extracted/507f1f77bcf86cd799439012/figure_1.png",
                "file_size": 512000,
                "source_type": "extracted",
                "document_id": "507f1f77bcf86cd799439012",
                "uploaded_date": "2025-01-01T10:00:00",
                "user_storage_used": 524288000,
                "user_storage_remaining": 549453824
            }
        }


class ImageInDB(BaseModel):
    """Image model stored in database"""
    user_id: str
    filename: str
    file_path: str
    file_size: int
    source_type: str = "uploaded"
    document_id: Optional[str] = None
    uploaded_date: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# API RESPONSE MODELS
# ============================================================================

class ApiResponse(BaseModel):
    """Standardized API response wrapper"""
    success: bool = Field(..., description="Whether the request was successful")
    message: str = Field(..., description="Response message")
    data: Optional[dict] = Field(None, description="Response data payload")
    errors: Optional[list] = Field(None, description="List of errors if any")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")

    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "message": "Operation completed successfully",
                "data": {"id": "507f1f77bcf86cd799439011"},
                "errors": None,
                "timestamp": "2025-01-01T10:00:00"
            }
        }


class PaginatedResponse(BaseModel):
    """Paginated API response with metadata"""
    success: bool = Field(..., description="Whether the request was successful")
    message: str = Field(..., description="Response message")
    data: list = Field(..., description="List of items")
    pagination: dict = Field(..., description="Pagination metadata")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")

    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "message": "Items retrieved successfully",
                "data": [{"id": "507f1f77bcf86cd799439011"}],
                "pagination": {
                    "current_page": 1,
                    "total_pages": 10,
                    "page_size": 10,
                    "total_items": 100
                },
                "timestamp": "2025-01-01T10:00:00"
            }
        }


# ============================================================================
# Annotation Schemas
# ============================================================================

class CoordinateInfo(BaseModel):
    """Annotation coordinates"""
    x: float = Field(..., description="X coordinate (percentage)")
    y: float = Field(..., description="Y coordinate (percentage)")
    width: float = Field(..., description="Width (percentage)")
    height: float = Field(..., description="Height (percentage)")

    class Config:
        schema_extra = {
            "example": {
                "x": 25.5,
                "y": 30.1,
                "width": 10.2,
                "height": 15.8
            }
        }


class AnnotationCreate(BaseModel):
    """Annotation creation request"""
    image_id: str = Field(..., description="ID of the image being annotated")
    text: str = Field(..., min_length=1, max_length=1000, description="Annotation text")
    coords: CoordinateInfo = Field(..., description="Annotation coordinates")

    class Config:
        schema_extra = {
            "example": {
                "image_id": "507f1f77bcf86cd799439013",
                "text": "Núcleo celular identificado",
                "coords": {
                    "x": 25.5,
                    "y": 30.1,
                    "width": 10.2,
                    "height": 15.8
                }
            }
        }


class AnnotationResponse(BaseModel):
    """Annotation response model"""
    id: str = Field(alias="_id", serialization_alias="_id")
    user_id: str
    image_id: str
    text: str
    coords: CoordinateInfo
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "_id": "507f1f77bcf86cd799439014",
                "user_id": "507f1f77bcf86cd799439011",
                "image_id": "507f1f77bcf86cd799439013",
                "text": "Núcleo celular identificado",
                "coords": {
                    "x": 25.5,
                    "y": 30.1,
                    "width": 10.2,
                    "height": 15.8
                },
                "created_at": "2025-01-01T10:00:00",
                "updated_at": "2025-01-01T10:00:00"
            }
        }

