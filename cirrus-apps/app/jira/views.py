from flask import render_template, request, session, flash, send_from_directory
from app import app
import os
from jira import JIRA

JIRA_SERVER = 'https://jira.ucar.edu'
JIRA_PROJECT_ID = '18470'
JIRA_ISSUE_TYPE = '10903'  # Story
JIRA_EPIC_LINK = 'CCPP-108'  # User Requests Epic
JIRA_EPIC_FIELD = 'customfield_10281'

def get_jira_client():
    """Initialize Jira client with Personal Access Token (Bearer auth)"""
    pat_token = os.getenv('JIRA_PAT')
    
    if not pat_token:
        raise ValueError("JIRA_PAT must be set in environment")
    
    # Create JIRA client and override session headers for Bearer token auth
    jira = JIRA(server=JIRA_SERVER, options={'server': JIRA_SERVER})
    jira._session.headers.update({
        'Authorization': f'Bearer {pat_token}',
        'Accept': 'application/json'
    })
    
    return jira

@app.route('/request-app', methods=['GET', 'POST'])
def request_app():
    if request.method == 'POST':
        try:
            jira = get_jira_client()
            
            # Build description from form data
            description = f"""Hello,

I have an application that I would like to host.

Submitted by: {request.form['submitter_name']} ({request.form['submitter_email']})

Link to GitHub repository: {request.form['github_repo']}
GitHub branch: {request.form['github_branch']}
Helm chart folder: {request.form['helm_folder']}
URL to use: {request.form['app_url']}

Thank you"""
            
            # Create issue dictionary
            issue_dict = {
                'project': {'id': JIRA_PROJECT_ID},
                'summary': 'Add new application to CIRRUS',
                'description': description,
                'issuetype': {'id': JIRA_ISSUE_TYPE},
                JIRA_EPIC_FIELD: JIRA_EPIC_LINK
            }
            
            # Create the issue
            new_issue = jira.create_issue(fields=issue_dict)
            flash(f'Success! Ticket {new_issue.key} created successfully. View it at: {JIRA_SERVER}/browse/{new_issue.key}', 'success')
            
        except Exception as e:
            flash(f'Error creating ticket: {str(e)}', 'danger')
    
    return render_template('request-app.html')
