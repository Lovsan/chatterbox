# filepath: /workspaces/chatterbox/socketio_events.py
from flask_socketio import emit
from flask import session
from models import User, Message, db

def register_socketio_events(socketio, app):
    """
    Register SocketIO event handlers.
    
    Args:
        socketio: The SocketIO instance.
        app: The Flask app instance.
    """
    
    @socketio.on('send_message')
    def handle_send_message_event(data):
        """
        Handle the 'send_message' event.
        
        Args:
            data: A dictionary containing the message data.
        """
        # Log the message event
        app.logger.info(f"{data['username']} has sent message to {data['recipient']}: {data['message']}")
        
        # Find the recipient user by username
        recipient = User.query.filter_by(username=data['recipient']).first()
        
        if recipient:
            # Create a new message and add it to the database
            new_message = Message(
                user_id=session["user_id"],
                recipient_id=recipient.id,
                text=data['message']
            )
            db.session.add(new_message)
            db.session.commit()
            
            # Emit the 'receive_message' event to all connected clients
            emit('receive_message', data, broadcast=True)