import json
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

from pymongo import MongoClient
from pymongo.errors import PyMongoError
from bson import json_util


# ============================================================
# CONFIGURATION
# ============================================================

from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI")

DATABASE_NAME = os.getenv("MONGODB_DB") or os.getenv("DATABASE_NAME", "koralink")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "knowledge")

JSON_FILE = Path(os.getenv("KNOWLEDGE_JSON_FILE", Path(__file__).with_name("koralink_new.json")))
BACKUP_DIR = Path(__file__).with_name("data") / "backups"


# ============================================================
# CONNECT TO MONGODB
# ============================================================

def connect_to_mongodb():
    try:
        print("Connecting to MongoDB...")

        if not MONGO_URI:
            print("\nERROR: MONGO_URI environment variable is not set.")
            print("Set your MongoDB Atlas connection string first.")
            sys.exit(1)

        client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=10000
        )

        client.admin.command("ping")

        print("MongoDB connection successful.")

        db = client[DATABASE_NAME]
        collection = db[COLLECTION_NAME]

        return client, collection

    except Exception as e:
        print("\nMongoDB connection failed.")
        print("Error:", e)
        sys.exit(1)


# ============================================================
# LOAD JSON
# ============================================================

def load_json():

    if not JSON_FILE.exists():
        print(f"\nERROR: JSON file was not found:")
        print(JSON_FILE)
        sys.exit(1)

    try:

        print("\nLoading JSON...")
        print(JSON_FILE)

        with open(JSON_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        # JSON is directly a list
        if isinstance(data, list):

            documents = data

        # JSON contains records inside a dictionary
        elif isinstance(data, dict):

            if "data" in data and isinstance(data["data"], list):
                documents = data["data"]

            elif "faqs" in data and isinstance(data["faqs"], list):
                documents = data["faqs"]

            elif "knowledge" in data and isinstance(data["knowledge"], list):
                documents = data["knowledge"]

            elif "questions" in data and isinstance(data["questions"], list):
                documents = data["questions"]

            else:
                documents = [data]

        else:

            print("ERROR: Unsupported JSON structure.")
            sys.exit(1)

        print(f"Loaded {len(documents)} records from JSON.")

        return documents

    except json.JSONDecodeError as e:

        print("\nInvalid JSON file.")
        print("Error:", e)
        sys.exit(1)

    except Exception as e:

        print("\nCould not read JSON.")
        print("Error:", e)
        sys.exit(1)


# ============================================================
# CREATE QUESTION KEY
# ============================================================

def create_question_key(question):

    if not question:
        return ""

    # Convert question to a normalized form.
    #
    # Example:
    #
    # "How do I check my balance?"
    #
    # becomes:
    #
    # "how do i check my balance?"
    #

    question = str(question).strip().lower()

    # Remove repeated spaces
    question = " ".join(question.split())

    return question


# ============================================================
# PREPARE DOCUMENTS
# ============================================================

def prepare_documents(documents):

    cleaned_documents = []

    seen_question_keys = set()

    for number, document in enumerate(documents, start=1):

        if not isinstance(document, dict):

            print(
                f"Skipping invalid record #{number}: "
                f"{document}"
            )

            continue

        document = dict(document)

        # Remove MongoDB _id from JSON.
        # MongoDB will keep its own _id.
        document.pop("_id", None)

        question = document.get("question")

        if not question:

            print(
                f"WARNING: Record #{number} has no question. "
                f"Skipping."
            )

            continue

        question_key = create_question_key(question)

        if not question_key:

            print(
                f"WARNING: Record #{number} has an empty question. "
                f"Skipping."
            )

            continue

        # Detect duplicate questions inside the JSON itself.
        if question_key in seen_question_keys:

            print(
                f"WARNING: Duplicate question in JSON:"
            )
            print(f"  {question}")

            continue

        seen_question_keys.add(question_key)

        # Add normalized key.
        document["question_key"] = question_key

        cleaned_documents.append(document)

    return cleaned_documents


# ============================================================
# UPSERT DOCUMENTS
# ============================================================

def upsert_documents(collection, documents):

    if not documents:

        print("\nNo valid documents to upload.")
        return

    print("\n======================================")
    print("UPLOADING KNOWLEDGE")
    print("======================================")


def replace_documents(collection, documents):
    """Replace only the knowledge collection, keeping a recoverable backup."""
    if not documents:
        raise RuntimeError("Refusing to replace MongoDB knowledge with an empty JSON file.")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"knowledge_mongodb_backup_{timestamp}.json"
    existing = list(collection.find({}))
    backup_file.write_text(json_util.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Backed up {len(existing)} existing knowledge records to: {backup_file}")

    try:
        collection.delete_many({})
        collection.insert_many(documents, ordered=True)
    except Exception:
        print("Replacement failed; restoring the previous knowledge records from memory...")
        collection.delete_many({})
        if existing:
            collection.insert_many(existing, ordered=True)
        print(f"Previous records restored. Backup retained at: {backup_file}")
        raise

    print(f"Replaced knowledge collection with {len(documents)} JSON records.")
    print(f"Backup retained at: {backup_file}")

    inserted = 0
    updated = 0
    failed = 0

    now = datetime.now(timezone.utc)

    for document in documents:

        try:

            question_key = document["question_key"]

            # When a question is translated, keep updating the existing
            # MongoDB record by its preserved source-language wording.
            source_question = create_question_key(document.get("question_en"))
            match_conditions = [{"question_key": question_key}]
            if source_question and source_question != question_key:
                match_conditions.extend([
                    {"question_key": source_question},
                    {"question": document.get("question_en")}
                ])

            # Add/update timestamp
            document["updated_at"] = now

            # Find existing question and update it.
            #
            # If it doesn't exist, MongoDB creates it.
            #

            result = collection.update_one(

                {"$or": match_conditions},

                {
                    "$set": document,

                    "$setOnInsert": {
                        "created_at": now
                    }
                },

                upsert=True
            )

            if result.upserted_id is not None:

                inserted += 1

                print(
                    f"[ADDED] {document.get('question')}"
                )

            elif result.modified_count > 0:

                updated += 1

                print(
                    f"[UPDATED] {document.get('question')}"
                )

            else:

                print(
                    f"[UNCHANGED] {document.get('question')}"
                )

        except PyMongoError as e:

            failed += 1

            print(
                f"\nFAILED: {document.get('question')}"
            )

            print("Error:", e)

    print("\n======================================")
    print("UPLOAD SUMMARY")
    print("======================================")

    print(f"New questions added : {inserted}")
    print(f"Questions updated   : {updated}")
    print(f"Failed              : {failed}")

    print("======================================")


# ============================================================
# CREATE INDEXES
# ============================================================

def create_indexes(collection):

    try:

        print("\nCreating indexes...")

        # Used to find/update questions quickly.
        collection.create_index(
            "question_key"
        )

        # Useful for filtering active knowledge.
        collection.create_index(
            "active"
        )

        # Useful for categories.
        collection.create_index(
            "category"
        )

        # Useful for language filtering.
        collection.create_index(
            "language"
        )

        print("Indexes created successfully.")

    except Exception as e:

        print("\nWARNING: Could not create indexes.")
        print("Error:", e)


# ============================================================
# VERIFY DATABASE
# ============================================================

def verify_database(collection):

    try:

        count = collection.count_documents({})

        print("\n======================================")
        print("MONGODB IMPORT COMPLETE")
        print("======================================")

        print(f"Database   : {DATABASE_NAME}")
        print(f"Collection : {COLLECTION_NAME}")
        print(f"Documents  : {count}")

        print("======================================")

        # Show a sample document
        print("\nTesting MongoDB read...")

        sample = collection.find_one({})

        if sample:

            print("MongoDB read test successful.")

            print("\nSample document:")

            print(
                json.dumps(
                    sample,
                    indent=2,
                    ensure_ascii=False,
                    default=str
                )
            )

        else:

            print(
                "WARNING: Collection is empty."
            )

    except Exception as e:

        print("\nDatabase verification failed.")
        print("Error:", e)


# ============================================================
# MAIN
# ============================================================

def main():

    print("======================================")
    print("KORALINK JSON → MONGODB SYNC")
    print("======================================")

    replace_mode = "--replace-knowledge" in sys.argv[1:]
    unknown_args = [arg for arg in sys.argv[1:] if arg != "--replace-knowledge"]
    if unknown_args:
        raise SystemExit(f"Unknown argument(s): {' '.join(unknown_args)}")

    # --------------------------------------------------------
    # 1. Load JSON
    # --------------------------------------------------------

    documents = load_json()

    # --------------------------------------------------------
    # 2. Clean documents
    # --------------------------------------------------------

    documents = prepare_documents(documents)

    print(
        f"\nPrepared {len(documents)} valid documents."
    )

    # --------------------------------------------------------
    # 3. Connect MongoDB
    # --------------------------------------------------------

    client, collection = connect_to_mongodb()

    try:

        # ----------------------------------------------------
        # 4. Upload/update or explicitly replace knowledge
        # ----------------------------------------------------
        if replace_mode:
            replace_documents(collection, documents)
        else:
            upsert_documents(collection, documents)

        # ----------------------------------------------------
        # 5. Create indexes
        # ----------------------------------------------------

        create_indexes(
            collection
        )

        # ----------------------------------------------------
        # 6. Verify
        # ----------------------------------------------------

        verify_database(
            collection
        )

    finally:

        client.close()

        print(
            "\nMongoDB connection closed."
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
