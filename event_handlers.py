# Description: This file contains the event handlers for the SocketIO events.


# import
from datetime import datetime, timezone
from flask_socketio import emit, join_room, leave_room
from flask import session
from models import User, Message, db


def register_event_handlers(socketio, app):
    """
    Register SocketIO event handlers.
    
    Args:
        socketio: The SocketIO instance.
        app: The Flask app instance.
    """
    

    @socketio.on("send_message")
    def handle_send_message(data):
        """
        Handle the "send_message" event.
        
        Args:
            data: A dictionary containing the message data.
        Data:
            username: The sender's username.
            recipient: The recipient's username.
            message: The message text.
        """

        # Log the message event
        # app.logger.info(f"{data["username"]} has sent message to {data["recipient"]}: {data["message"]}")
        
        # Check if the user is logged in
        if "user_id" not in session:
            emit("error", {"error": "You must be logged in to send messages!"})
            return

        # get the data
        username = data.get("username")
        recipient = data.get("recipient")
        message = data.get("message")

        #
        # CHECK USERNAME
        #
        # Check if username is provided
        if not username:
            emit("error", {"error": "Username is required!"})
            return
        # Check if the sender's username matches the logged in user's username
        if username != session["username"]:
            emit("error", {"error": "You are not authorized to send messages on behalf of other users!"})
            return

        #
        # CHECK MESSAGE
        #
        # Check if the message is empty
        if not message:
            emit("error", {"error": "Message cannot be empty!"})
            return
        # Check message length
        if len(message) > 500:
            emit("error", {"error": "Message must be at most 500 characters long!"})
            return
        
        #
        # CHECK & GET RECIPIENT
        #
        # Check if recipient is provided
        if not recipient:
            emit("error", {"error": "Recipient is required!"})
            return
        # Find the recipient user by username
        recipient_db = User.query.filter_by(username=recipient).first()
        # Check if the recipient exists
        if not recipient_db:
            emit("error", {"error": "Recipient not found!"})
            return
        
        # Create a new message
        new_message = Message(
            user_id=session["user_id"],
            recipient_id=recipient_db.id,
            text=message,
            timestamp=datetime.now(timezone.utc)
        )
        # Add the new message to the database
        db.session.add(new_message)
        db.session.commit()
        
        # Emit the "receive_message" event to the intended recipient and sender
        recipient_room = f"user_{recipient_db.id}"
        sender_room = f"user_{session['user_id']}"
        emit("receive_message", data, room=recipient_room)
        emit("receive_message", data, room=sender_room)


    @socketio.on("connect")
    def handle_connect():
        """
        Handle the "connect" event.
        """

        # Join the user's room
        user_id = session.get("user_id")
        if user_id:
            join_room(f"user_{user_id}")
    

    @socketio.on("disconnect")
    def handle_disconnect():
        """
        Handle the "disconnect" event.
        """
        
        # Leave the user's room
        user_id = session.get("user_id")
        if user_id:
            leave_room(f"user_{user_id}")