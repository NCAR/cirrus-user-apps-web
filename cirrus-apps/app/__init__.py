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

# Jira "new issue" forms, all filed under the User Requests epic (CCPP-108)
# and differing only in the pre-filled summary prefix. Works whether or not the
# visitor is signed in to Jira; Jira asks for login first, then opens the form.
_JIRA_NEW_ISSUE = (
    "https://jira.ucar.edu/secure/CreateIssueDetails!init.jspa"
    "?pid=18470&issuetype=10903&customfield_10281=CCPP-108&summary="
)
app.jinja_env.globals["JIRA_HELP_URL"] = _JIRA_NEW_ISSUE + "User%20Request:"
app.jinja_env.globals["JIRA_ACCESS_URL"] = _JIRA_NEW_ISSUE + "Access%20Request:"
app.jinja_env.globals["JIRA_WORKLOAD_URL"] = _JIRA_NEW_ISSUE + "Add%20Workload:"

from app.main import views
from app.jira import views
from app.metrics import views
from app.cluster_status import views