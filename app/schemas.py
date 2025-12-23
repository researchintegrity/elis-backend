"""
Pydantic schemas for request/response validation
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime
from typing import Optional, Dict, List, Any
from bson import ObjectId
from enum import Enum
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
    exif_metadata: Optional[Dict[str, Any]] = Field(None, description="EXIF metadata extracted from image")

    class Config:
        schema_extra = {
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "filename": "figure_1.png",
                "file_path": "/workspace/507f1f77bcf86cd799439011/images/extracted/507f1f77bcf86cd799439012/figure_1.png",
                "file_size": 512000,
                "source_type": "extracted",
                "document_id": "507f1f77bcf86cd799439012",
                "exif_metadata": {"Make": "Canon", "Model": "Canon EOS 5D Mark IV"}
            }
        }


class CopyMoveAnalysisRequest(BaseModel):
    """Request to start copy-move analysis"""
    method: int = Field(2, ge=1, le=5, description="Detection method (1-5)")

    class Config:
        schema_extra = {
            "example": {
                "method": 2
            }
        }


class ImageResponse(BaseModel):
    """Image response model"""
    id: str = Field(alias="_id")
    user_id: str
    filename: str
    file_path: str
    file_size: int
    source_type: str = Field(description="extracted|uploaded|panel")
    document_id: Optional[str] = None
    # Panel extraction fields (only for source_type='panel')
    source_image_id: Optional[str] = None
    panel_id: Optional[str] = None
    panel_type: Optional[str] = None
    bbox: Optional[Dict[str, float]] = None  # {x0, y0, x1, y1}
    exif_metadata: Optional[Dict[str, Any]] = None
    # PDF extraction metadata (only for source_type='extracted' from PDFs)
    pdf_page: Optional[int] = None
    page_bbox: Optional[Dict[str, float]] = None  # {x0, y0, x1, y1} in pixel coordinates
    extraction_mode: Optional[str] = None  # 'normal' or 'safe'
    original_filename: Optional[str] = None  # Original filename before _id rename
    # Image type management
    image_type: List[str] = Field(default_factory=list, description="User-editable image types (e.g., 'figure', 'table', 'equation')")
    
    # Analysis fields
    analysis_status: Dict[str, str] = Field(default_factory=dict, description="Status of various analyses (e.g. {'copy_move': 'processing'})")
    analysis_results: Dict[str, Dict] = Field(default_factory=dict, description="Results of analyses")
    analysis_ids: List[str] = Field(default_factory=list, description="List of analysis IDs involving this image")
    
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
                "filename": "507f1f77bcf86cd799439013.png",
                "file_path": "workspace/507f1f77bcf86cd799439011/images/extracted/507f1f77bcf86cd799439012/507f1f77bcf86cd799439013.png",
                "file_size": 512000,
                "source_type": "extracted",
                "document_id": "507f1f77bcf86cd799439012",
                "source_image_id": None,
                "panel_id": None,
                "panel_type": None,
                "bbox": None,
                "pdf_page": 4,
                "page_bbox": {"x0": 40.0, "y0": 59.28, "x1": 553.6, "y1": 492.0},
                "extraction_mode": "normal",
                "original_filename": "p-4-x0-40.000-y0-59.280-x1-553.600-y1-492.000-1.png",
                "image_type": ["figure"],
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
    analysis_ids: List[str] = Field(default_factory=list)


class PaginatedImageResponse(BaseModel):
    """Paginated response for image listing - supports efficient gallery pagination"""
    items: List["ImageResponse"] = Field(description="List of images for current page")
    total: int = Field(description="Total number of images matching the query")
    page: int = Field(description="Current page number (1-indexed)")
    per_page: int = Field(description="Number of items per page")
    total_pages: int = Field(description="Total number of pages")
    has_next: bool = Field(description="Whether there is a next page")
    has_prev: bool = Field(description="Whether there is a previous page")
    
    class Config:
        schema_extra = {
            "example": {
                "items": [],
                "total": 150,
                "page": 1,
                "per_page": 24,
                "total_pages": 7,
                "has_next": True,
                "has_prev": False
            }
        }


# ============================================================================
# IMAGE TYPE MANAGEMENT MODELS
# ============================================================================

class ImageTypeListResponse(BaseModel):
    """Response for listing all image types in the system"""
    types: List[str] = Field(description="List of all unique image types used in system")
    count: int = Field(description="Total number of unique types")

    class Config:
        schema_extra = {
            "example": {
                "types": ["figure", "table", "equation", "text"],
                "count": 4
            }
        }


class ImageTypesUpdateRequest(BaseModel):
    """Request to add types to an image"""
    types: List[str] = Field(..., description="List of types to add (duplicates ignored)")

    class Config:
        schema_extra = {
            "example": {
                "types": ["figure", "graph"]
            }
        }


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

class PolygonPoint(BaseModel):
    """A single point in a polygon"""
    x: float = Field(..., description="X coordinate (percentage)")
    y: float = Field(..., description="Y coordinate (percentage)")


class CoordinateInfo(BaseModel):
    """Annotation coordinates - supports rectangles, ellipses, and polygons"""
    x: float = Field(0, description="X coordinate (percentage)")
    y: float = Field(0, description="Y coordinate (percentage)")
    width: float = Field(0, description="Width (percentage)")
    height: float = Field(0, description="Height (percentage)")
    points: Optional[List[PolygonPoint]] = Field(None, description="Polygon points (for polygon shapes)")

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
    text: str = Field("", max_length=1000, description="Annotation text/description")
    coords: CoordinateInfo = Field(..., description="Annotation coordinates")
    type: Optional[str] = Field("manipulation", description="Annotation type/label (e.g., manipulation, copy-move, splicing)")
    group_id: Optional[int] = Field(None, description="Group ID for related annotations (e.g., copy-move pairs)")
    shape_type: Optional[str] = Field("rectangle", description="Shape type: rectangle, ellipse, or polygon")

    class Config:
        schema_extra = {
            "example": {
                "image_id": "507f1f77bcf86cd799439013",
                "text": "Detected manipulation region",
                "coords": {
                    "x": 25.5,
                    "y": 30.1,
                    "width": 10.2,
                    "height": 15.8
                },
                "type": "manipulation",
                "group_id": None,
                "shape_type": "rectangle"
            }
        }


class AnnotationResponse(BaseModel):
    """Annotation response model"""
    id: str = Field(alias="_id", serialization_alias="_id")
    user_id: str
    image_id: str
    text: str
    coords: CoordinateInfo
    type: Optional[str] = "manipulation"
    group_id: Optional[int] = None
    shape_type: Optional[str] = "rectangle"
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


# ============================================================================
# Watermark Removal Schemas
# ============================================================================

class WatermarkRemovalRequest(BaseModel):
    """Watermark removal request"""
    aggressiveness_mode: int = Field(
        default=2,
        ge=1,
        le=3,
        description="Watermark removal aggressiveness (1=explicit only, 2=text+graphics, 3=all graphics)"
    )

    class Config:
        schema_extra = {
            "example": {
                "aggressiveness_mode": 2
            }
        }


class WatermarkRemovalInitiationResponse(BaseModel):
    """Watermark removal task initiation response"""
    document_id: str
    task_id: str
    status: str = Field(description="Task status: queued")
    aggressiveness_mode: int
    message: str

    class Config:
        schema_extra = {
            "example": {
                "document_id": "507f1f77bcf86cd799439012",
                "task_id": "abc123def456",
                "status": "queued",
                "aggressiveness_mode": 2,
                "message": "Watermark removal queued with mode 2"
            }
        }


class WatermarkRemovalStatusResponse(BaseModel):
    """Watermark removal status response"""
    document_id: str
    status: str = Field(description="Status: not_started|queued|processing|completed|failed")
    aggressiveness_mode: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    message: Optional[str] = None
    output_filename: Optional[str] = None
    output_size: Optional[int] = None
    cleaned_document_id: Optional[str] = None
    error: Optional[str] = None

    class Config:
        schema_extra = {
            "example": {
                "document_id": "507f1f77bcf86cd799439012",
                "status": "completed",
                "aggressiveness_mode": 2,
                "started_at": "2025-01-01T10:00:00",
                "completed_at": "2025-01-01T10:05:00",
                "message": "Watermark removal successful",
                "output_filename": "research_paper_watermark_removed_m2.pdf",
                "output_size": 1990000,
                "cleaned_document_id": "507f1f77bcf86cd799439015",
                "error": None
            }
        }


# ============================================================================
# Panel Extraction Schemas
# ============================================================================

class PanelExtractionRequest(BaseModel):
    """Panel extraction request"""
    image_ids: list[str] = Field(..., description="MongoDB IDs of selected images to extract panels from")
    model_type: str = Field(
        default="default",
        description="Optional YOLO model selection"
    )

    class Config:
        schema_extra = {
            "example": {
                "image_ids": ["507f1f77bcf86cd799439013", "507f1f77bcf86cd799439014"],
                "model_type": "default"
            }
        }


class PanelExtractionInitiationResponse(BaseModel):
    """Panel extraction task initiation response"""
    task_id: str
    status: str = Field(description="Task status: queued")
    image_ids: list[str]
    message: str

    class Config:
        schema_extra = {
            "example": {
                "task_id": "abc123def456xyz",
                "status": "queued",
                "image_ids": ["507f1f77bcf86cd799439013", "507f1f77bcf86cd799439014"],
                "message": "Panel extraction queued for 2 images"
            }
        }


class PanelExtractionStatusResponse(BaseModel):
    """Panel extraction status response"""
    task_id: str
    status: str = Field(description="Status: queued|processing|completed|failed")
    image_ids: list[str]
    extracted_panels_count: int = 0
    extracted_panels: Optional[list[ImageResponse]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    message: Optional[str] = None
    error: Optional[str] = None

    class Config:
        schema_extra = {
            "example": {
                "task_id": "abc123def456xyz",
                "status": "completed",
                "image_ids": ["507f1f77bcf86cd799439013"],
                "extracted_panels_count": 3,
                "extracted_panels": [
                    {
                        "_id": "507f1f77bcf86cd799439020",
                        "user_id": "507f1f77bcf86cd799439011",
                        "filename": "panel_00001.png",
                        "file_path": "/workspace/507f1f77bcf86cd799439011/images/panels/panel_00001.png",
                        "file_size": 45000,
                        "source_type": "panel",
                        "document_id": None,
                        "source_image_id": "507f1f77bcf86cd799439013",
                        "panel_id": "panel_00001",
                        "panel_type": "Blots",
                        "bbox": {"x0": 100.5, "y0": 150.3, "x1": 450.8, "y1": 520.2},
                        "uploaded_date": "2025-01-01T10:05:00",
                        "user_storage_used": 524288000,
                        "user_storage_remaining": 549453824
                    }
                ],
                "started_at": "2025-01-01T10:00:00",
                "completed_at": "2025-01-01T10:02:30",
                "message": "Panel extraction successful. Extracted 3 panels",
                "error": None
            }
        }


# ============================================================================
# CBIR (Content-Based Image Retrieval) SCHEMAS
# ============================================================================

class CBIRIndexRequest(BaseModel):
    """Request to index images in CBIR system"""
    image_ids: Optional[List[str]] = Field(None, description="Specific image IDs to index. If None, indexes all user images.")
    labels: Optional[List[str]] = Field(None, description="Labels to apply to indexed images")

    class Config:
        json_schema_extra = {
            "example": {
                "image_ids": ["507f1f77bcf86cd799439013", "507f1f77bcf86cd799439014"],
                "labels": ["Western Blot", "Microscopy"]
            }
        }


class CBIRSearchRequest(BaseModel):
    """Request to search for similar images"""
    image_id: str = Field(..., description="Query image ID")
    top_k: int = Field(10, ge=1, le=100, description="Number of similar images to return")
    labels: Optional[List[str]] = Field(None, description="Filter results by labels")

    class Config:
        json_schema_extra = {
            "example": {
                "image_id": "507f1f77bcf86cd799439013",
                "top_k": 10,
                "labels": ["Western Blot"]
            }
        }


class CBIRSearchResult(BaseModel):
    """Single CBIR search result"""
    cbir_id: Optional[int] = Field(None, description="CBIR internal ID")
    distance: float = Field(..., description="Distance/dissimilarity score (lower is more similar)")
    similarity_score: float = Field(..., description="Similarity score (higher is more similar)")
    image_path: str = Field(..., description="Path to the similar image")
    image_id: Optional[str] = Field(None, description="MongoDB image ID")
    filename: Optional[str] = Field(None, description="Image filename")
    file_size: Optional[int] = Field(None, description="Image file size in bytes")
    source_type: Optional[str] = Field(None, description="Image source type")
    document_id: Optional[str] = Field(None, description="Source document ID if extracted")
    image_type: List[str] = Field(default_factory=list, description="Image type labels")
    cbir_labels: List[str] = Field(default_factory=list, description="CBIR index labels")


class CBIRSearchResponse(BaseModel):
    """CBIR search response with results"""
    query_image_id: str
    top_k: int
    labels_filter: Optional[List[str]] = None
    matches_count: int
    matches: List[CBIRSearchResult]


class CBIRDeleteRequest(BaseModel):
    """Request to delete images from CBIR index"""
    image_ids: List[str] = Field(..., min_length=1, description="Image IDs to remove from index")

    class Config:
        json_schema_extra = {
            "example": {
                "image_ids": ["507f1f77bcf86cd799439013", "507f1f77bcf86cd799439014"]
            }
        }


class CBIRStatusResponse(BaseModel):
    """CBIR service status"""
    service: str = "cbir"
    healthy: bool
    message: str
    timestamp: datetime


# ============================================================================
# ANALYSIS SCHEMAS
# ============================================================================

class CopyMoveMethod(str, Enum):
    """Detection method for copy-move analysis"""
    DENSE = "dense"  # Dense matching (original copy-move-detection module, methods 1-5)
    KEYPOINT = "keypoint"  # Keypoint matching (copy-move-detection-keypoint module, cross-image only)


class KeypointDescriptor(str, Enum):
    """Descriptor types for keypoint-based copy-move detection"""
    CV_SIFT = "cv_sift"  # OpenCV SIFT
    CV_RSIFT = "cv_rsift"  # OpenCV RootSIFT (default, recommended)
    VLFEAT_SIFT_HEQ = "vlfeat_sift_heq"  # VLFeat SIFT with histogram equalization


class AnalysisType(str, Enum):
    SINGLE_IMAGE_COPY_MOVE = "single_image_copy_move"
    CROSS_IMAGE_COPY_MOVE = "cross_image_copy_move"
    TRUFOR = "trufor"
    CBIR_SEARCH = "cbir_search"
    PROVENANCE = "provenance"


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisBase(BaseModel):
    """Base analysis model"""
    type: AnalysisType
    user_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: AnalysisStatus = AnalysisStatus.PENDING
    error: Optional[str] = None


class SingleImageAnalysisCreate(BaseModel):
    """Request to create a single image analysis (dense method only)"""
    image_id: str
    # Single-image detection only supports dense method
    method: CopyMoveMethod = Field(
        CopyMoveMethod.DENSE,
        description="Detection method for single image (only 'dense' supported)"
    )
    # Dense method sub-parameter (1-5)
    dense_method: int = Field(2, ge=1, le=5, description="Dense method variant (1-5)")


class CrossImageAnalysisCreate(BaseModel):
    """Request to create a cross image analysis"""
    source_image_id: str
    target_image_id: str
    method: CopyMoveMethod = Field(
        CopyMoveMethod.KEYPOINT,
        description="Detection method: 'keypoint' (recommended) or 'dense'"
    )
    # Dense method sub-parameter (only used when method='dense')
    dense_method: int = Field(2, ge=1, le=5, description="Dense method variant (1-5), only used when method='dense'")
    # Keypoint descriptor (only used when method='keypoint')
    descriptor: KeypointDescriptor = Field(
        KeypointDescriptor.CV_RSIFT,
        description="Keypoint descriptor type, only used when method='keypoint'"
    )


class AnalysisResult(BaseModel):
    """Generic analysis result container"""
    # Method can be string ('keypoint', 'dense') for copy-move or int for legacy
    method: Optional[Any] = None
    dense_method: Optional[int] = None  # Sub-method for dense detection (1-5)
    descriptor: Optional[str] = None  # Keypoint descriptor type (cv_sift, cv_rsift, vlfeat_sift_heq)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    matches_image: Optional[str] = None
    clusters_image: Optional[str] = None
    visualization: Optional[str] = None
    files: Optional[List[str]] = None
    logs: Optional[Dict[str, Any]] = None
    
    # CBIR specific fields
    query_image_id: Optional[str] = None
    top_k: Optional[int] = None
    labels_filter: Optional[List[str]] = None
    matches_count: Optional[int] = None
    matches: Optional[List[CBIRSearchResult]] = None

    class Config:
        extra = "allow"


class AnalysisResponse(AnalysisBase):
    """Analysis response model"""
    id: str = Field(alias="_id")
    source_image_id: str
    target_image_id: Optional[str] = None
    results: Optional[AnalysisResult] = None

    @field_validator('id', mode='before')
    @classmethod
    def convert_object_id(cls, v):
        """Convert MongoDB ObjectId to string"""
        if isinstance(v, ObjectId):
            return str(v)
        return v

    class Config:
        json_encoders = {ObjectId: str}
        populate_by_name = True

