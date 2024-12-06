# Description: This file contains the database models for the application.


# import
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy


# create the database object
db = SQLAlchemy()


# User database model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    messages = db.relationship('Message', backref='user', lazy=True)


# Message database model
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now(), nullable=False)