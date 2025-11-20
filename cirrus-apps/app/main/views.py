from flask import render_template, request, session, flash, send_from_directory
from app import app
import yaml
import os

@app.route('/')
def home():
    # Load applications from YAML file
    apps_file = os.path.join(app.root_path, 'apps.yaml')
    with open(apps_file, 'r') as f:
        applications = yaml.safe_load(f)
    
    return render_template('home.html', applications=applications)

@app.route('/templates/navbar.html')
def navbar():
    return render_template('navbar.html')