import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient
from werkzeug.security import generate_password_hash

# Load variables from .env file if present
load_dotenv()

# Check both common naming conventions
uri = os.getenv('MONGO_URI') or os.getenv('MONGODB_URI')
dbname = os.getenv('DATABASE_NAME', 'koralink')

if not uri:
    raise SystemExit('Error: Neither MONGO_URI nor MONGODB_URI is set in the environment or .env file.')

if len(sys.argv) != 4:
    raise SystemExit('Usage: python create_agent.py "Name" email password')

name, email, password = sys.argv[1], sys.argv[2].lower(), sys.argv[3]

try:
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    client.admin.command('ping')
    db = client[dbname]

    db.agents.update_one(
        {'email': email},
        {
            '$set': {
                'name': name,
                'email': email,
                'password_hash': generate_password_hash(password),
                'role': 'agent',
                'active': True,
                'online': False
            }
        },
        upsert=True
    )
    print(f'Agent created/updated: {email}')

except Exception as err:
    sys.exit(f'Database operation failed: {err}')

finally:
    if 'client' in locals():
        client.close()