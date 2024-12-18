# NOT USED RIGHT NOW, BUT WILL BE USED IN THE FUTURE
# NOT USED RIGHT NOW, BUT WILL BE USED IN THE FUTURE
# NOT USED RIGHT NOW, BUT WILL BE USED IN THE FUTURE
# Description: This file contains the code for the socket handlers.


# import
from flask_socketio import emit, join_room, leave_room
from flask import session
from helpers import login_required
from flask_session import Session
from models import User, db, Message


# register socket handlers
def register_socket_handlers(socketio):

    # join room
    @socketio.on("join")
    @login_required
    def handle_join(data):
        join_room(session["user_id"])

    # leave room
    @socketio.on("leave")
    @login_required
    def handle_leave(data):
        leave_room(session["user_id"])
    
    # send message
    @socketio.on("send_message")
    @login_required
    def handle_send_message(data):

        # get data
        recipient_id = data.get("recipient_id")
        text = data.get("text")

        # if not recipient_id or message_text
        if not recipient_id or not text:
            return emit("error", {"message": "Recipient and message are required!"})
        
        # check if recipient_id is not the same as user_id
        if recipient_id == session["user_id"]:
            return emit("error", {"message": "You cannot send a message to yourself!"})
        
        # if recipient not found
        recipient = User.query.get(recipient_id)
        if not recipient:
            return emit("error", {"message": "Recipient not found!"})
        
        # strip message text
        text = text.strip()

        # if message > 500 characters
        if len(text) > 500:
            return emit("error", {"message": "Message must be at most 500 characters long!"})

        # create a new message
        new_message = Message(
            user_id=session["user_id"],
            recipient_id=recipient_id,
            text=text
        )
    
        # add message to database
        db.session.add(new_message)
        db.session.commit()

        # prepare message data to send to sender and recipient
        message_data = {
            "user_id": new_message.user_id,
            "recipient_id": new_message.recipient_id,
            "text": new_message.text,
            "timestamp": new_message.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }

        # send message to sender and recipient
        emit("receive_message", message_data, room=session["user_id"])
        emit("receive_message", message_data, room=recipient_id)