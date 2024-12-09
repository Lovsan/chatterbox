# Description: This file contains the database models for the application.


# import
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy


# create the database object
db = SQLAlchemy()


# User database model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)


# Message database model
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now(timezone.utc), nullable=False)

    sender = db.relationship('User', foreign_keys=[user_id], backref='sent_messages')
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='received_messages')