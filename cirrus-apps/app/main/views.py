from flask import render_template, request, session, flash, send_from_directory
from app import app
import yaml
import json
import os
import requests
from datetime import datetime

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
    
    # Fetch status from each status page
    for page in config['status_pages']:
        try:
            url = f"{config['uptime_kuma_url']}/api/status-page/{page['slug']}"
            print(f"Fetching: {url}")
            
            response = requests.get(url, timeout=5)
            print(f"Response status code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Response data for {page['name']}:")
                print(json.dumps(data, indent=2))
                
                # Get overall status - if any monitor is down, page is down
                page['status'] = 'UP'
                if 'publicGroupList' in data:
                    for group in data['publicGroupList']:
                        for monitor in group.get('monitorList', []):
                            print(f"Monitor: {monitor.get('name')}, Status: {monitor.get('status')}")
                            if monitor.get('status') != 1:  # 1 = UP in Uptime Kuma
                                page['status'] = 'DOWN'
                                break
                else:
                    print("No publicGroupList found in response")
            else:
                print(f"Non-200 response: {response.text}")
                page['status'] = 'UNKNOWN'
        except Exception as e:
            print(f"Exception for {page['name']}: {str(e)}")
            page['status'] = 'UNKNOWN'
    
    config['last_check'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S MST')
    
    return render_template('status.html', config=config)

@app.route('/sla')
def sla():
    return render_template('sla.html')

@app.route('/templates/navbar.html')
def navbar():
    return render_template('navbar.html')