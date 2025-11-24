from flask import render_template, request, session, flash, send_from_directory
from app import app
import yaml
import os
import requests
import datetime

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/apps')
def apps():
    apps_file = os.path.join(app.root_path, 'apps.yaml')
    with open(apps_file, 'r') as f:
        applications = yaml.safe_load(f)
    
    return render_template('apps.html', applications=applications)

@app.route('/status')
def status():
    status_file = os.path.join(app.root_path, 'status_monitors.yaml')
    with open(status_file, 'r') as f:
        config = yaml.safe_load(f)
    
    for page in config['status_pages']:
        try:
            response = requests.get(
                f"{config['uptime_kuma_url']}/api/status-page/{page['slug']}",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                page['status'] = 'UP'
                if 'publicGroupList' in data:
                    for group in data['publicGroupList']:
                        for monitor in group.get('monitorList', []):
                            if monitor.get('status') != 1:
                                page['status'] = 'DOWN'
                                break
            else:
                page['status'] = 'UNKNOWN'
        except:
            page['status'] = 'UNKNOWN'
    
    config['last_check'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S MST')
    
    return render_template('status.html', config=config)

@app.route('/sla')
def sla():
    return render_template('sla.html')

@app.route('/templates/navbar.html')
def navbar():
    return render_template('navbar.html')