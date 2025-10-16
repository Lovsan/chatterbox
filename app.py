# Description: This file contains the main code for the Flask app.


# import
from flask import Flask, render_template, request, flash, redirect, session, url_for, jsonify
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


@app.route("/")
def home():
    """
    Home page
    """

    return render_template("home.html")


@app.route("/author")
def author():
    """
    Author page
    """

    return render_template("author.html")


@app.route("/login", methods=["GET", "POST"])
@logout_required
def login():
    """
    Handle user login
    Logout required.
    """

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


@app.route("/logout")
def logout():
    """
    Handle user logout
    """

    # clear session and flash message
    session.clear()
    flash("Logged out successfully!")
    return redirect(url_for("home"))


@app.route("/register", methods=["GET", "POST"])
@logout_required
def register():
    """
    Handle user registration
    Logout required.
    """

    # IF POST: create a new user
    if request.method == "POST":

        # get form data
        username = request.form.get("username")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm-password")
        license = request.form.get("license")

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
        if password != confirm_password:
            flash("Passwords do not match!")
            return redirect(url_for("register"))
        
        # check license agreement
        if not license:
            flash("You must agree to the license agreement!")
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


@app.route("/chat")
@login_required
def chat():
    """
    Renders the chat page and handles message retrieval.
    LOGIN REQUIRED.
    GET:
        - Retrieves messages between the current user and a selected recipient.
    Note:
        - New messages are now handled by the websocket.
    Returns:
        - Renders the chat page with messages and recipient details.
    """

    recipient_id = request.args.get("recipient_id", type=int)
    recipient = User.query.get(recipient_id) if recipient_id else None

    return render_template(
        "chat.html",
        recipient=recipient,
        recipient_id=recipient_id
    )


@app.route("/chat/start", methods=["POST"])
@login_required
def chat_start():
    """
    Handle starting a chat with a new user.
    Login required.
    """

    payload = request.get_json(silent=True)
    if payload:
        username = (payload.get("username") or "").strip()
    else:
        username = (request.form.get("username") or "").strip()

    if not username:
        message = "Recipient username is required!"
        if payload is not None:
            return jsonify({"message": message}), 400
        flash(message)
        return redirect(url_for("chat"))

    if username == session["username"]:
        message = "You cannot start a chat with yourself!"
        if payload is not None:
            return jsonify({"message": message}), 400
        flash(message)
        return redirect(url_for("chat"))

    recipient = User.query.filter_by(username=username).first()
    if not recipient:
        message = "User not found!"
        if payload is not None:
            return jsonify({"message": message}), 404
        flash(message)
        return redirect(url_for("chat"))

    if payload is not None:
        return jsonify({
            "conversation": {
                "id": recipient.id,
                "name": recipient.username,
                "display_name": recipient.username,
                "type": "direct"
            }
        }), 201

    return redirect(url_for("chat", recipient_id=recipient.id))


@app.route("/chat/user-list")
@login_required
def user_list():
    """
    Endpoint to return the list of users the current user has chatted with.
    """
    # Query to get recent users the current user has chatted with, along with the last message timestamp
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
        func.max(Message.timestamp).desc()  # Order by the last message timestamp in descending order
    ).all()

    # Create a list of dictionaries containing user id and username
    users = [{'id': user.id, 'username': user.username} for user, _ in recent_users]

    # Return the list of users as a JSON response
    return jsonify({'users': users})


@app.route("/chat/open-conversations")
@login_required
def open_conversations():
    """Return a list of conversations for the tab bar."""

    current_user_id = session["user_id"]

    messages = Message.query.filter(
        (Message.user_id == current_user_id) | (Message.recipient_id == current_user_id)
    ).order_by(Message.timestamp.desc()).all()

    conversations = {}
    user_cache = {}
    for message in messages:
        other_id = message.recipient_id if message.user_id == current_user_id else message.user_id
        if other_id in conversations:
            continue
        other_user = message.recipient if message.user_id == current_user_id else message.sender
        if other_user is None:
            other_user = user_cache.get(other_id)
            if other_user is None:
                other_user = User.query.get(other_id)
                user_cache[other_id] = other_user
        if not other_user:
            continue
        conversations[other_id] = {
            "id": other_user.id,
            "name": other_user.username,
            "display_name": other_user.username,
            "type": "direct",
            "last_message": message.text,
            "last_timestamp": message.timestamp.isoformat() if message.timestamp else None
        }

    return jsonify({"conversations": list(conversations.values())})


@app.route("/chat/conversation/<int:partner_id>/messages")
@login_required
def conversation_messages(partner_id):
    """Return the message history for a conversation."""

    current_user_id = session["user_id"]
    partner = User.query.get_or_404(partner_id)

    messages = Message.query.filter(
        ((Message.user_id == current_user_id) & (Message.recipient_id == partner_id)) |
        ((Message.user_id == partner_id) & (Message.recipient_id == current_user_id))
    ).order_by(Message.timestamp.asc()).all()

    serialized = []
    for message in messages:
        serialized.append({
            "id": message.id,
            "text": message.text,
            "timestamp": message.timestamp.isoformat() if message.timestamp else None,
            "sender": {
                "id": message.user_id,
                "username": message.sender.username if message.sender else None
            },
            "recipient": {
                "id": message.recipient_id,
                "username": message.recipient.username if message.recipient else None
            }
        })

    return jsonify({
        "conversation": {
            "id": partner.id,
            "name": partner.username,
            "display_name": partner.username,
            "type": "direct"
        },
        "messages": serialized
    })


# verify async mode
print(f"SocketIO async mode: {socketio.async_mode}")

# run the app
if __name__ == "__main__":
    socketio.run(app, debug=True)