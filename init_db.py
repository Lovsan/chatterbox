# Description: This script is used to create the database tables.


# import
from app import app
from models import db


# create the database tables
with app.app_context():
    db.create_all()
    print("Database tables created")