from flask import render_template, request, session, flash, send_from_directory
from app import app
import yaml
import os

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/status')
def status():
    # Load status monitors from YAML file
    status_file = os.path.join(app.root_path, 'status_monitors.yaml')
    with open(status_file, 'r') as f:
        monitors = yaml.safe_load(f)
    
    return render_template('status.html', monitors=monitors)

@app.route('/apps')
def apps():
    # Load applications from YAML file
    apps_file = os.path.join(app.root_path, 'apps.yaml')
    with open(apps_file, 'r') as f:
        applications = yaml.safe_load(f)
    
    return render_template('apps.html', applications=applications)

@app.route('/templates/navbar.html')
def navbar():
    return render_template('navbar.html')