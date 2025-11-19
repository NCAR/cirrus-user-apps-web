import secrets
from pathlib import Path

from flask import Flask
from flask_session import Session

app = Flask(__name__)
app.app_context().push()

SECRET_FILE_PATH = Path(".flask_secret")
try:
    with SECRET_FILE_PATH.open("r") as secret_file:
        app_secret_key = secret_file.read()
except FileNotFoundError:
    # Let's create a cryptographically secure code in that file
    with SECRET_FILE_PATH.open("w") as secret_file:
        app_secret_key = secrets.token_hex(32)
        secret_file.write(app_secret_key)

app.config['SECRET_KEY'] = app_secret_key
app.config["SESSION_PERMANENT"] = False
app.config['SESSION_TYPE'] = 'filesystem'

Session(app)

from app.main import views