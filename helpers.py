# Description: Helper functions for the application


from functools import wraps
from flask import session, flash, redirect


# login required
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            flash("You must be logged in to access this page.")
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function