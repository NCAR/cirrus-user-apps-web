from flask import render_template, request, redirect
from app import app
from urllib.parse import urlencode

JIRA_SERVER = 'https://jira.ucar.edu'
JIRA_PROJECT_ID = '18470'
JIRA_ISSUE_TYPE = '10903'  # Story
JIRA_EPIC_LINK = 'CCPP-108'  # User Requests Epic
JIRA_EPIC_FIELD = 'customfield_10281'

@app.route('/request-app', methods=['GET', 'POST'])
def request_app():
    if request.method == 'POST':
        description = f"""Hello,

I have an application that I would like to host on CIRRUS.

Submitted by: {request.form['submitter_name']} ({request.form['submitter_email']})

Link to GitHub repository: {request.form['github_repo']}
GitHub branch: {request.form['github_branch']}
Helm chart folder: {request.form['helm_folder']}

Thank you"""

        params = urlencode({
            'pid': JIRA_PROJECT_ID,
            'issuetype': JIRA_ISSUE_TYPE,
            'summary': 'Add new application to CIRRUS',
            'description': description,
            JIRA_EPIC_FIELD: JIRA_EPIC_LINK,
            'reporter': request.form['reporter_username'],  # their Jira username e.g. "ncote"
        })

        jira_url = f"{JIRA_SERVER}/secure/CreateIssueDetails!init.jspa?{params}"
        return redirect(jira_url)

    return render_template('request-app.html')