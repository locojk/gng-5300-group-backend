import json
import os
from pathlib import Path
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, CollectionInvalid
from utils.logger import logger
from utils.env_loader import load_platform_specific_env

# Dynamically load environment variables based on OS and hostname
load_platform_specific_env()


class MongoDBClient:
    def __init__(self, db_name=None):
        self.db_name = db_name if db_name else os.getenv('MONGO_DATABASE', 'fitness_db')
        mongo_user = os.getenv('MONGO_USER')
        mongo_password = os.getenv('MONGO_PASSWORD')
        mongo_host = os.getenv('MONGO_HOST', 'localhost')
        mongo_port = os.getenv('MONGO_PORT', '27017')
        self.uri = f"mongodb://{mongo_user}:{mongo_password}@{mongo_host}:{mongo_port}/{self.db_name}?authSource=admin"
        logger.info(f"MongoDB URI constructed: {self.uri}")
        self.client = None
        self.db = None
        self._connect()

    def _connect(self):
        """Connect to MongoDB and test connection"""
        if not self.client:
            try:
                logger.info(f"Attempting to connect to MongoDB: {self.db_name}")
                self.client = MongoClient(self.uri)
                self.db = self.client[self.db_name]
                self.client.admin.command('ping')  # Test connection
                logger.info(f"Successfully connected to MongoDB database: {self.db_name}")
            except ConnectionFailure as e:
                logger.error(f"Failed to connect to MongoDB: {str(e)}")
                raise

    def __enter__(self):
        """Ensure self.db is initialized in context manager"""
        self._connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed.")
            self.client = None
            self.db = None

    def _load_validation_schema(self, schema_filename):
        # Set schema root path
        base_path = Path(__file__).parent.parent / 'schema'
        schema_path = next(base_path.glob(f'**/{schema_filename}'), None)

        if schema_path is None or not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_filename} in {base_path}")

        with open(schema_path, 'r') as f:
            return json.load(f)

    def _ensure_validation(self, collection_name, schema_filename):
        """
        Set or update JSON Schema validation rules for a collection
        :param collection_name: Name of the collection
        :param schema_filename: Validation schema file stored in the schema directory
        """
        validation_schema = self._load_validation_schema(schema_filename)
        try:
            self.db.create_collection(collection_name)
        except CollectionInvalid:
            pass  # Collection already exists

        self.db.command({
            "collMod": collection_name,
            "validator": validation_schema,
            "validationLevel": "strict"  # Strict mode
        })
        logger.info(f"Validation schema applied to collection: {collection_name}")

    # All database operation methods below use self.db and self.client; no need to reconnect or close
    def insert_one(self, collection_name, data):
        """Insert a single document into the specified collection, setting is_deleted to False by default"""
        logger.info(f"Inserting one document into collection: {collection_name}")
        data["is_deleted"] = False
        collection = self.db[collection_name]
        result = collection.insert_one(data)
        logger.info(f"Document inserted with ID: {result.inserted_id}")
        return result.inserted_id

    def find_one(self, collection_name, query, include_deleted=False):
        """Find a single document, ignoring soft-deleted documents by default"""
        logger.info(f"Finding one document in collection: {collection_name} with query: {query}")
        if not include_deleted:
            query["is_deleted"] = False
        collection = self.db[collection_name]
        result = collection.find_one(query)
        logger.info(f"Find one result: {result}")
        return result

    def update_one(self, collection_name, query, update_data):
        """Update a single document"""
        logger.info(f"Updating one document in collection: {collection_name} with query: {query}")
        collection = self.db[collection_name]
        result = collection.update_one(query, {'$set': update_data})
        logger.info(f"Update result: {result.modified_count} document(s) modified")
        return result

    def delete_one(self, collection_name, query, soft_delete=True):
        """Delete a single document, performing a soft delete by default"""
        logger.info(f"Deleting one document in collection: {collection_name} with query: {query}")
        collection = self.db[collection_name]
        if soft_delete:
            update_data = {"is_deleted": True}
            result = collection.update_one(query, {'$set': update_data})
            logger.info(f"Soft delete result: {result.modified_count} document(s) modified")
        else:
            result = collection.delete_one(query)
            logger.info(f"Physical delete result: {result.deleted_count} document(s) deleted")
        return result

    def find_many(self, collection_name, query, include_deleted=False, sort=None, limit=0, skip=0):
        """Find multiple documents, supporting sorting, limit, and skip options"""
        logger.info(
            f"Finding many documents in collection: {collection_name} with query: {query}, sort: {sort}, limit: {limit}, skip: {skip}")
        if not include_deleted:
            query["is_deleted"] = False
        collection = self.db[collection_name]
        cursor = collection.find(query)

        if sort:
            cursor = cursor.sort(sort)
        if skip > 0:
            cursor = cursor.skip(skip)
        if limit > 0:
            cursor = cursor.limit(limit)

        result_list = list(cursor)
        logger.info(f"Find many result: {len(result_list)} document(s) found")
        return result_list

    def insert_many(self, collection_name, data_list):
        """Insert multiple documents into the specified collection, setting is_deleted to False by default"""
        logger.info(f"Inserting many documents into collection: {collection_name}")
        for data in data_list:
            data["is_deleted"] = False
        collection = self.db[collection_name]
        result = collection.insert_many(data_list)
        logger.info(f"Documents inserted with IDs: {result.inserted_ids}")
        return result.inserted_ids

    def delete_many(self, collection_name, query, soft_delete=True):
        """Delete multiple documents, performing a soft delete by default"""
        logger.info(f"Deleting many documents in collection: {collection_name} with query: {query}")
        collection = self.db[collection_name]
        if soft_delete:
            update_data = {"is_deleted": True}
            result = collection.update_many(query, {'$set': update_data})
            logger.info(f"Soft delete result: {result.modified_count} document(s) modified")
        else:
            result = collection.delete_many(query)
            logger.info(f"Physical delete result: {result.deleted_count} document(s) deleted")
        return result

    def aggregate(self, collection_name, pipeline):
        """Perform MongoDB aggregation operation"""
        logger.info(f"Aggregating documents in collection: {collection_name} with pipeline: {pipeline}")
        collection = self.db[collection_name]
        result = collection.aggregate(pipeline)
        return list(result)

    def count_documents(self, collection_name, query):
        """Count the number of documents that match the query"""
        logger.info(f"Counting documents in collection: {collection_name} with query: {query}")
        collection = self.db[collection_name]
        count = collection.count_documents(query)
        logger.info(f"Count result: {count} document(s) found")
        return count
