"""
MongoDB database connection and configuration
"""
from pymongo import MongoClient
from fastapi import HTTPException, status
import os
from dotenv import load_dotenv

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "elis_system")


class MongoDBConnection:
    """Singleton class for MongoDB connection"""
    _instance = None
    _client = None
    _db = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self):
        """Connect to MongoDB"""
        try:
            self._client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=5000)
            self._client.admin.command('ping')
            self._db = self._client[DATABASE_NAME]
            print(f"✅ Connected to MongoDB: {DATABASE_NAME}")
        except Exception as e:
            print(f"❌ MongoDB connection failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"MongoDB connection failed: {str(e)}"
            )

    def disconnect(self):
        """Disconnect from MongoDB"""
        if self._client:
            self._client.close()
            print("✅ Disconnected from MongoDB")

    def get_database(self):
        """Get database instance"""
        if self._db is None:
            self.connect()
        return self._db

    def get_collection(self, collection_name: str):
        """Get a specific collection"""
        db = self.get_database()
        return db[collection_name]


# Global database connection instance
db_connection = MongoDBConnection()


def get_users_collection():
    """Get users collection with indexes"""
    collection = db_connection.get_collection("users")
    
    # Create indexes for better performance
    collection.create_index("username", unique=True)
    collection.create_index("email", unique=True)
    
    return collection


def get_documents_collection():
    """Get documents collection with indexes for PDF uploads"""
    collection = db_connection.get_collection("documents")
    
    # Create indexes for better performance
    collection.create_index("user_id")
    collection.create_index("uploaded_date")
    collection.create_index([("user_id", 1), ("uploaded_date", -1)])
    
    return collection


def get_images_collection():
    """Get images collection with indexes for extracted/uploaded images"""
    collection = db_connection.get_collection("images")
    
    # Create indexes for better performance
    collection.create_index("user_id")
    collection.create_index("document_id")
    collection.create_index("uploaded_date")
    collection.create_index("source_type")
    collection.create_index([("user_id", 1), ("source_type", 1)])
    collection.create_index([("document_id", 1), ("source_type", 1)])
    
    return collection


def get_database():
    """Get database instance"""
    return db_connection.get_database()
