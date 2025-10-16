# Description: Helper functions for the application


# import libraries
from flask import session, flash, redirect, url_for
from functools import wraps


def login_required(f):
    """
    Decorator function to require login.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            flash("You must be logged in to access this page.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def logout_required(f):
    """
    Decorator function to require logOUT.
    """
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id"):
            flash("You are already logged in.")
            return redirect(url_for("chat"))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator function to require admin privileges."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Administrator access required.")
            return redirect(url_for("chat"))
        return f(*args, **kwargs)

    return decorated_function