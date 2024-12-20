#!/bin/bash

# Check if the database file exists
if [ ! -f "./instance/chatterbox.db" ]; then
  echo "Database does not exist. Initializing the database..."
  # Run the database initialization script
  python init_db.py
else
  echo "Database already exists. Skipping initialization..."
fi

# Execute the command passed as arguments (CMD from Dockerfile)
exec "$@"