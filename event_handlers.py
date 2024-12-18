# Description: This file contains the event handlers for the SocketIO events.


# import
from flask_socketio import emit
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
        """

        # Log the message event
        # app.logger.info(f"{data["username"]} has sent message to {data["recipient"]}: {data["message"]}")
        
        # Find the recipient user by username
        recipient = User.query.filter_by(username=data["recipient"]).first()
        
        # Check if the recipient exists
        if not recipient:
            emit("error", {"error": "Recipient not found!"})
            return
        
        # Strip message text
        message_text = data["message"].strip()
        
        # Check message length
        if len(message_text) > 500:
            emit("error", {"error": "Message must be at most 500 characters long!"})
            return
        
        # Create a new message
        new_message = Message(
            user_id=session["user_id"],
            recipient_id=recipient.id,
            text=message_text
        )
        # Add the new message to the database
        db.session.add(new_message)
        db.session.commit()
        
        # Emit the "receive_message" event to all connected clients
        # TODO: THIS IS NOT SAFE! FIX THIS!
        emit("receive_message", data, broadcast=True)