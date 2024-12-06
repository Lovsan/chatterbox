# Description: This file contains the main code for the Flask app.


# import
from flask import Flask, render_template, request, flash, redirect, session
from flask_session import Session
from models import db, User, Message
from werkzeug.security import generate_password_hash, check_password_hash
import os
from functools import wraps
from helpers import *


# create app
app = Flask(__name__)

# reload templates
app.config["TEMPLATES_AUTO_RELOAD"] = True

# configure database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///chatterbox.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# configure session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)


# home page
@app.route("/")
def home():
    return render_template("home.html")


# author page
@app.route("/author")
def author():
    return render_template("author.html")


# login page (logOUT required)
@app.route("/login", methods=["GET", "POST"])
@logout_required
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # check if username and password are provided
        if not username or not password:
            flash("Username and password are required!")
            return redirect("/login")
        
        # check username and password
        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password, password):
            flash("Invalid username or password!")
            return redirect("/login")
        
        # store user id in session
        session["user_id"] = user.id
        session["username"] = user.username
        flash("Logged in successfully!")
        return redirect("/chat")
        
    return render_template("login.html")


# logout
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully!")
    return redirect("/")


# register page (logOUT required)
@app.route("/register", methods=["GET", "POST"])
@logout_required
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # check if username and password are provided
        if not username or not password:
            flash("Username and password are required!")
            return redirect("/register")
        
        # check username characters and length
        if not username.isalnum() or len(username) > 20:
            flash("Username must contain only letters and digits and be at most 20 characters long!")
            return redirect("/register")
        
        # check password length and characters
        if len(password) < 8 or not any(char.isupper() for char in password) or not any(char.islower() for char in password) or not any(char.isdigit() for char in password):
            flash("Password must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, and one digit!")
            return redirect("/register")

        # check password confirmation
        confirm_password = request.form.get("confirm-password")
        if password != confirm_password:
            flash("Passwords do not match!")
            return redirect("/register")
        
        # check if username already exists
        user = User.query.filter_by(username=username).first()
        if user:
            flash("Username already exists!")
            return redirect("/register")
        
        # create a new user
        hashed_password = generate_password_hash(password, method="pbkdf2:sha256")
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully! Please log in.")
        return redirect("/login")
    
    return render_template("register.html")


# TODO: chat page (login required)
@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat():
    return render_template("chat.html")


# run the app
if __name__ == "__main__":
    app.run(debug=True)