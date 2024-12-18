# Description: This file contains the main code for the Flask app.


# import
from flask import Flask, render_template, request, flash, redirect, session, url_for
from flask_session import Session
from flask_socketio import SocketIO
from models import db, User, Message
from werkzeug.security import generate_password_hash, check_password_hash
from helpers import login_required, logout_required
from sqlalchemy import func
from event_handlers import register_event_handlers


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

# initialize SocketIO
socketio = SocketIO(app)
register_event_handlers(socketio, app)


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
    # IF POST: check username and password
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # check if username and password are provided
        if not username or not password:
            flash("Username and password are required!")
            return redirect(url_for("login"))
        
        # check username and password
        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password, password):
            flash("Invalid username or password!")
            return redirect(url_for("login"))
        
        # store user id in session
        session["user_id"] = user.id
        session["username"] = user.username
        flash("Logged in successfully!")
        return redirect(url_for("chat"))
        
    return render_template("login.html")


# logout
@app.route("/logout")
def logout():
    # clear session and flash message
    session.clear()
    flash("Logged out successfully!")
    return redirect(url_for("home"))


# register page (logOUT required)
@app.route("/register", methods=["GET", "POST"])
@logout_required
def register():
    # IF POST: create a new user
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # check if username and password are provided
        if not username or not password:
            flash("Username and password are required!")
            return redirect(url_for("register"))
        
        # check username characters and length
        if not username.isalnum() or len(username) > 20:
            flash("Username must contain only letters and digits and be at most 20 characters long!")
            return redirect(url_for("register"))
        
        # check password length and characters
        if len(password) < 8 or len(password) > 200 or not any(char.isupper() for char in password) or not any(char.islower() for char in password) or not any(char.isdigit() for char in password):
            flash("Password must be between 8 and 200 characters long and contain at least one uppercase letter, one lowercase letter, and one digit!")
            return redirect(url_for("register"))

        # check password confirmation
        confirm_password = request.form.get("confirm-password")
        if password != confirm_password:
            flash("Passwords do not match!")
            return redirect(url_for("register"))
        
        # check if username already exists
        user = User.query.filter_by(username=username).first()
        if user:
            flash("Username already exists!")
            return redirect(url_for("register"))
        
        # create a new user
        hashed_password = generate_password_hash(password, method="pbkdf2:sha256")
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        # flash message and redirect to login
        flash("Account created successfully! Please log in.")
        return redirect(url_for("login"))
    
    # render register page
    return render_template("register.html")


# chat page (login required)
@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat():
    # GET RECENT USERS
    #
    # this did not work:
    # recent_users = User.query.join(
    #    Message, (Message.user_id == session["user_id"]) | (Message.recipient_id == session["user_id"])
    #    ).filter(User.id != session["user_id"]).distinct().all()
    #
    # this kinda works:
    # recent_users_ids = db.session.query(Message.user_id).filter(
    #     Message.recipient_id == session["user_id"]
    # ).union(
    #     db.session.query(Message.recipient_id).filter(Message.user_id == session["user_id"])
    # ).distinct()
    # recent_users = User.query.filter(User.id.in_(recent_users_ids)).all()
    #
    # this fully works:
    recent_users = db.session.query(
        User, func.max(Message.timestamp).label("last_message_time")
    ).join(
        Message, (Message.user_id == User.id) | (Message.recipient_id == User.id)
    ).filter(
        (Message.user_id == session["user_id"]) | (Message.recipient_id == session["user_id"])
    ).filter(
        User.id != session["user_id"]
    ).group_by(
        User.id
    ).order_by(
        func.max(Message.timestamp).desc()
    ).all()
    
    # get recipient
    recipient_id = request.args.get("recipient_id", type=int)
    recipient = User.query.get(recipient_id) if recipient_id else None

    # get recent messages
    messages = []
    if recipient:
        messages = Message.query.filter(
            ((Message.user_id == session["user_id"]) & (Message.recipient_id == recipient_id)) |
            ((Message.user_id == recipient_id) & (Message.recipient_id == session["user_id"]))
        ).order_by(Message.timestamp.asc()).all()
    
    # IF POST: add message to database
    if request.method=="POST":
        recipient_id = request.form.get("recipient_id", type=int)
        message_text = request.form.get("message")

        # check if recipient and message are provided
        if not recipient_id or not message_text:
            flash("Recipient and message are required!")
            return redirect(url_for("chat", recipient_id=recipient_id))
        
        # check if recipient exists
        recipient = User.query.get(recipient_id)
        if not recipient:
            flash("Recipient not found!")
            return redirect(url_for("chat"))

        # strip message text
        message_text = message_text.strip()
        
        # check message length
        if len(message_text) > 500:
            flash("Message must be at most 500 characters long!")
            return redirect(url_for("chat", recipient_id=recipient_id))
        
        # create a new message and add it to database
        new_message = Message(
            user_id=session["user_id"],
            recipient_id=recipient_id,
            text=message_text
        )
        db.session.add(new_message)
        db.session.commit()

        # flash message and redirect to chat
        return redirect(url_for("chat", recipient_id=recipient_id))

    # return chat page
    return render_template(
        "chat.html",
        recent_users=recent_users,
        messages=messages,
        recipient=recipient,
        recipient_id=recipient_id
        )


# start chat with a new user (login required)
@app.route("/chat/start", methods=["POST"])
@login_required
def chat_start():
    # get recipient username
    username = request.form.get("username").strip()

    # check if username is provided
    if not username:
        flash("Recipient username is required!")
        return redirect(url_for("chat"))
    
    # check if recipient is not the current user
    if username == session["username"]:
        flash("You cannot start a chat with yourself!")
        return redirect(url_for("chat"))
    
    # check if recipient exists
    recipient = User.query.filter_by(username=username).first()
    if not recipient:
        flash("User not found!")
        return redirect(url_for("chat"))
    
    # redirect to chat with recipient
    return redirect(url_for("chat", recipient_id=recipient.id))


# run the app
if __name__ == "__main__":
    socketio.run(app, debug=True)