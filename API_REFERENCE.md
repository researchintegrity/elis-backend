# ELIS API Reference

## Authentication

All endpoints require JWT token (except `/auth/`).

```bash
# Add to request headers:
Authorization: Bearer <token>
```

## Auth Endpoints

### Register
```
POST /auth/register
Content-Type: application/json

{
  "username": "user",
  "email": "user@example.com",
  "password": "password",
  "full_name": "Full Name"
}
```

### Login
```
POST /auth/login
Content-Type: application/x-www-form-urlencoded

username=user&password=password
```

Returns: `access_token`, `token_type`

## User Endpoints

```
GET /users/me                    # Get current user profile
PUT /users/me                    # Update profile
DELETE /users/me                 # Delete account
```

Request body for PUT:
```json
{
  "full_name": "Updated Name",
  "email": "new@example.com"
}
```

## Document Endpoints

```
POST /documents/upload           # Upload PDF
GET /documents                   # List documents
GET /documents/{doc_id}          # Get document details
DELETE /documents/{doc_id}       # Delete document
```

Upload:
```
POST /documents/upload
Content-Type: multipart/form-data

file: <PDF file>
```

Returns: `document_id`, `filename`, `file_size`, `extraction_status`

## Image Endpoints

```
GET /images                      # List images (paginated)
GET /images/{image_id}           # Get image details
DELETE /images/{image_id}        # Delete image
```

Response includes: `file_path`, `file_size`, `source_type` (extracted/uploaded/panel)

## Panel Extraction Endpoints

### Initiate Extraction
```
POST /images/extract-panels
Content-Type: application/json

{
  "image_ids": ["id1", "id2"],
  "model_type": "default"
}
```

Returns: `202 Accepted` with `task_id`

```json
{
  "task_id": "uuid-string",
  "status": "PENDING",
  "image_ids": ["id1", "id2"],
  "message": "Panel extraction queued"
}
```

### Check Status
```
GET /images/extract-panels/status/{task_id}
```

Returns:
- `PENDING`: Still processing
- `SUCCESS`: Complete with `extracted_panels` array
- `FAILURE`: Failed with `error` message

```json
{
  "task_id": "uuid",
  "status": "SUCCESS",
  "extracted_panels_count": 3,
  "extracted_panels": [
    {
      "id": "panel_id",
      "filename": "panel_00001.png",
      "source_image_id": "image_id",
      "panel_id": "1",
      "panel_type": "Graphs",
      "bbox": {
        "x0": 92.0,
        "y0": 48.0,
        "x1": 629.0,
        "y1": 430.0
      }
    }
  ]
}
```

### List Panels from Image
```
GET /images/{image_id}/panels
```

Returns: Array of all panels extracted from source image

## CBIR Endpoints (Content-Based Image Retrieval)

CBIR allows searching for visually similar images within the user's collection.

### Index Images
```
POST /cbir/index
Content-Type: application/json

{
  "image_ids": ["id1", "id2"],
  "labels": ["optional_label"]
}
```
Indexes specified images (or all user images if `image_ids` is omitted).

### Search Similar Images (Async)
```
POST /cbir/search
Content-Type: application/json

{
  "image_id": "query_image_id",
  "top_k": 10,
  "labels": ["filter_label"]
}
```
Starts an async search task. Returns `analysis_id` to poll status.

### Search Similar Images (Sync)
```
POST /cbir/search/sync
Content-Type: application/json

{
  "image_id": "query_image_id",
  "top_k": 10
}
```
Returns search results immediately.

### Search by Upload
```
POST /cbir/search/upload?top_k=10
Content-Type: multipart/form-data

file: <Image file>
```
Search using an uploaded image without storing it.

### Remove from Index
```
DELETE /cbir/index
Content-Type: application/json

{
  "image_ids": ["id1", "id2"]
}
```

## Analysis Endpoints

General endpoints for various image analysis tasks.

### Get Analysis Details
```
GET /analyses/{analysis_id}
```
Returns status and results for any analysis type (CBIR, Copy-Move, TruFor, Provenance).

### Copy-Move Detection (Cross-Image)
```
POST /analyses/copy-move/cross
Content-Type: application/json

{
  "source_image_id": "id1",
  "target_image_id": "id2",
  "method": "keypoint" 
}
```
Detects if content from source image was copied to target image.
`method` can be `keypoint` (default) or `dense`.

### TruFor Forgery Detection
```
POST /analyses/trufor
Content-Type: application/json

{
  "image_id": "id1"
}
```
Analyzes a single image for manipulation traces using TruFor model.

## Annotation Endpoints

```
GET /annotations                 # List annotations
POST /annotations                # Create annotation
GET /annotations/{anno_id}       # Get annotation
PUT /annotations/{anno_id}       # Update annotation
DELETE /annotations/{anno_id}    # Delete annotation
```

## Provenance Analysis Endpoints

Provenance analysis identifies content sharing relationships between images using keypoint matching and geometric verification.

### Start Provenance Analysis
```
POST /provenance/analyze
Content-Type: application/json

{
  "query_image_ids": ["id1", "id2"],
  "descriptor_type": "vlfeat_sift_heq",
  "alignment_strategy": "CV_MAGSAC",
  "min_area": 0.01,
  "min_keypoints": 20,
  "check_flip": true,
  "top_k_retrieval": 50,
  "max_depth": 2,
  "max_queue_size": 100,
  "same_label_only": false,
  "labels_filter": null,
  "search_scope": "user"
}
```

**Parameters:**
- `query_image_ids` (required): List of image IDs to start analysis from
- `descriptor_type`: Keypoint descriptor type (`vlfeat_sift_heq`, `opencv_sift`)
- `alignment_strategy`: Geometric verification method (`CV_MAGSAC`, `CV_RANSAC`)
- `min_area`: Minimum shared area ratio (0-1) for valid match
- `min_keypoints`: Minimum keypoints required per image
- `check_flip`: Check horizontally flipped images
- `top_k_retrieval`: Number of similar images to retrieve from CBIR
- `max_depth`: Maximum BFS traversal depth from query images
- `max_queue_size`: Maximum images to process in queue
- `same_label_only`: Only match images with same labels
- `search_scope`: `"user"` (own images) or `"global"` (admin only)

Returns: `202 Accepted` with `analysis_id`

```json
{
  "analysis_id": "uuid-string",
  "status": "pending",
  "status_url": "/api/v1/provenance/{analysis_id}",
  "message": "Provenance analysis started for 2 query image(s)"
}
```

### Get Analysis Status & Results
```
GET /provenance/{analysis_id}
```

Returns analysis status and results when complete:

```json
{
  "id": "analysis_id",
  "user_id": "user_id",
  "status": "completed",
  "query_image_ids": ["id1", "id2"],
  "config": {...},
  "created_at": "2025-01-01T00:00:00Z",
  "completed_at": "2025-01-01T00:01:00Z",
  "progress": {
    "stage": "completed",
    "images_processed": 15,
    "matched_pairs": 8,
    "processing_time_seconds": 45.2
  },
  "result": {
    "graph_nodes": [
      {"id": "image_id", "label": "filename.jpg", "is_query": true}
    ],
    "graph_edges": [
      {"from": "id1", "to": "id2", "weight": 0.85, "is_flipped": false}
    ],
    "spanning_tree_edges": [...],
    "connected_components": [[...], [...]],
    "total_images_analyzed": 15,
    "matched_pairs_count": 8,
    "processing_time_seconds": 45.2
  }
}
```

### Get Graph Data
```
GET /provenance/{analysis_id}/graph
```

Returns structured graph data for visualization:

```json
{
  "analysis_id": "uuid",
  "nodes": [
    {"id": "img1", "label": "image.jpg", "is_query": true}
  ],
  "edges": [
    {"from": "img1", "to": "img2", "weight": 0.85}
  ],
  "spanning_tree_edges": [...],
  "connected_components": [[...]],
  "statistics": {
    "total_images": 15,
    "matched_pairs": 8,
    "processing_time": 45.2
  }
}
```

### Get Visualization HTML
```
GET /provenance/{analysis_id}/visualization?width=800&height=600
```

Returns an embeddable HTML page with vis.js graph visualization.

Query parameters:
- `width`: Visualization width in pixels (400-2000)
- `height`: Visualization height in pixels (300-1500)

### List Analyses
```
GET /provenance/?skip=0&limit=20&status=completed
```

Returns paginated list of user's provenance analyses.

### Delete Analysis
```
DELETE /provenance/{analysis_id}
```

### Precompute Descriptors
```
POST /provenance/precompute-descriptors?descriptor_type=vlfeat_sift_heq
Content-Type: application/json

["image_id1", "image_id2", "image_id3"]
```

Pre-warms descriptor cache for faster analysis.

### Admin Endpoints

#### Cross-User Analysis (Admin Only)
```
POST /provenance/admin/cross-user-analysis
Content-Type: application/json

{
  "query_image_ids": ["id1"],
  "target_user_ids": ["user1", "user2"],
  "config": {...}
}
```

Searches for image sharing across different users.

#### Cleanup Old Descriptors (Admin Only)
```
POST /provenance/admin/cleanup-descriptors?days_old=30&user_id=optional_user
```

Removes cached descriptors older than specified days.

## Common Response Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 202 | Accepted (async) |
| 400 | Bad request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not found |
| 409 | Conflict (duplicate) |
| 422 | Validation error |
| 500 | Server error |

## Query Parameters

Most list endpoints support:

```
?skip=0           # Pagination offset
?limit=10         # Items per page
?sort=field       # Sort by field
```

## Error Response Format

```json
{
  "detail": "Error message describing what went wrong"
}
```

Or for validation errors:

```json
{
  "detail": [
    {
      "loc": ["body", "field_name"],
      "msg": "Field validation error",
      "type": "value_error"
    }
  ]
}
```

## Example Workflow

### 1. Register & Login
```bash
# Register
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "scientist",
    "email": "scientist@example.com",
    "password": "secure123",
    "full_name": "John Scientist"
  }'

# Login and save token
TOKEN=$(curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=scientist&password=secure123" \
  | jq -r '.access_token')
```

### 2. Upload Document
```bash
curl -X POST http://localhost:8000/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@research_paper.pdf"
```

### 3. Extract Panels
```bash
# Get image ID from document extraction
IMAGE_ID="..."

# Initiate panel extraction
TASK=$(curl -X POST http://localhost:8000/images/extract-panels \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"image_ids": ["'$IMAGE_ID'"], "model_type": "default"}' \
  | jq -r '.task_id')

# Check status
curl -X GET http://localhost:8000/images/extract-panels/status/$TASK \
  -H "Authorization: Bearer $TOKEN" | jq .
```

## Rate Limiting

No current rate limiting. Production deployment should add limits per user.

## Async Operations

Operations that process large files use async pattern:

1. Send request
2. Receive `202 Accepted` with `task_id`
3. Poll status endpoint until complete
4. Retrieve results when done

Typical polling interval: 1-5 seconds

## Pagination Example

```bash
# Get first 10 images
curl "http://localhost:8000/images?skip=0&limit=10" \
  -H "Authorization: Bearer $TOKEN"

# Get next 10
curl "http://localhost:8000/images?skip=10&limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

## Storage Quota

Each user has a storage quota (default 1GB). Responses include:

```json
{
  "user_storage_used": 524288000,
  "user_storage_remaining": 549453824
}
```

Attempting to upload beyond quota returns `400 Bad Request`.

## Interactive Exploration

Open http://localhost:8000/docs for interactive API testing with Swagger UI.
