"""
Authentication routes for user registration and login
"""
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from pymongo.errors import DuplicateKeyError

from app.schemas import UserRegister, UserLogin, TokenResponse, UserResponse
from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    JWT_EXPIRATION_HOURS
)
from app.db.mongodb import get_users_collection

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserRegister) -> dict:
    """
    Register a new user
    
    - **username**: Unique username (3-50 characters)
    - **email**: Valid email address
    - **password**: Password (minimum 4 characters)
    - **full_name**: Optional full name
    """
    collection = get_users_collection()
    
    # Check if user already exists
    existing_user = collection.find_one(
        {"$or": [{"username": user_data.username}, {"email": user_data.email}]}
    )
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered"
        )
    
    # Create new user document
    user_doc = {
        "username": user_data.username,
        "email": user_data.email,
        "hashed_password": hash_password(user_data.password),
        "full_name": user_data.full_name,
        "is_active": True,
        "created_at": __import__('datetime').datetime.utcnow(),
        "updated_at": __import__('datetime').datetime.utcnow()
    }
    
    try:
        result = collection.insert_one(user_doc)
        
        # Get created user
        created_user = collection.find_one({"_id": result.inserted_id})
        
        # Create token
        access_token = create_access_token(username=user_data.username)
        expires_delta = timedelta(hours=JWT_EXPIRATION_HOURS)
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": UserResponse(**created_user).dict(by_alias=True),
            "expires_in": int(expires_delta.total_seconds())
        }
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered"
        )


@router.post("/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> dict:
    """
    Login with username and password
    
    - **username**: Username or email
    - **password**: User password
    
    Returns JWT access token and user information
    """
    collection = get_users_collection()
    
    # Find user by username or email
    user = collection.find_one(
        {"$or": [{"username": form_data.username}, {"email": form_data.username}]}
    )
    
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    
    # Create token
    access_token = create_access_token(username=user["username"])
    expires_delta = timedelta(hours=JWT_EXPIRATION_HOURS)
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse(**user).dict(by_alias=True),
        "expires_in": int(expires_delta.total_seconds())
    }
