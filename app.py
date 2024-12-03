# Description: This file contains the main code for the Flask app.
from flask import Flask
from models import db, User, Message


# create the Flask app and configure database
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///chatterbox.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)


# main route/page
@app.route("/")
def home():
    return "Hello, World!"


# run the app
if __name__ == "__main__":
    app.run(debug=True)