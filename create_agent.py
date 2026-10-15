import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient
from werkzeug.security import generate_password_hash

# Load variables from .env file if present
load_dotenv()

# Check both common naming conventions
uri = os.getenv('MONGO_URI') or os.getenv('MONGODB_URI')
dbname = os.getenv('MONGODB_DB') or os.getenv('DATABASE_NAME', 'koralink')

if not uri:
    raise SystemExit('Error: Neither MONGO_URI nor MONGODB_URI is set in the environment or .env file.')

if len(sys.argv) not in (4, 5):
    raise SystemExit('Usage: python create_agent.py "Name" email password [agent|admin]')

name, email, password = sys.argv[1], sys.argv[2].lower(), sys.argv[3]
role = sys.argv[4].lower() if len(sys.argv) == 5 else 'agent'
if role not in ('agent', 'admin'):
    raise SystemExit('Role must be agent or admin.')

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
                'role': role,
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
