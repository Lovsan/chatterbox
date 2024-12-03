# Description: This script is used to create the database tables.
from app import app
from models import db


# create the database tables
with app.app_context():
    db.create_all()
    print("Database tables created")