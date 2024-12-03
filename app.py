# Description: This file contains the main code for the Flask app.
from flask import Flask, render_template
from models import db, User, Message


# create the Flask app and configure database
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///chatterbox.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)


# home page
@app.route("/")
def home():
    return render_template("home.html")


# author page
@app.route("/author")
def author():
    return render_template("author.html")


# login page
@app.route("/login", methods=["GET", "POST"])
def login():
    return render_template("login.html")


# register page
@app.route("/register", methods=["GET", "POST"])
def register():
    return render_template("register.html")


# run the app
if __name__ == "__main__":
    app.run(debug=True)