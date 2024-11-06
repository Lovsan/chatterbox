from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy

app = flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatterbox.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)