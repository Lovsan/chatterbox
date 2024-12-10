# Description: This script is used to create the database tables.


# import
import os
from app import app
from models import db


# database file path
db_path = os.path.join("instance", "chatterbox.db")

# check if the database file exists and remove it
if os.path.exists(db_path):
    # ask the user for confirmation
    print("Existing database will be REMOVED!")
    confirmation = input("Do you want to continue? (y/n): ")
    if confirmation.lower() != "y":
        print("Operation cancelled")
        exit()

    # remove the database file
    os.remove(db_path)
    print("Database file removed")

# create the database tables
with app.app_context():
    db.create_all()
    print("Database tables created")