from flask import render_template, request, session
from app import app
import yaml
import json
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/getting-started')
def getting_started():
    return render_template('getting-started.html')

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
            # Fetch the public status page HTML
            status_url = f"{config['uptime_kuma_url']}/status/{page['slug']}"
            response = requests.get(status_url, timeout=5)
            
            if response.status_code == 200:
                # Extract the preloadData JSON embedded in the HTML
                import re
                match = re.search(r"window\.preloadData = (\{.*?\});", response.text)
                
                if match:
                    # The JSON uses single quotes, need to convert to valid JSON
                    json_str = match.group(1)
                    json_str = json_str.replace("'", '"').replace('null', 'null').replace('True', 'true').replace('False', 'false')
                    preload_data = json.loads(json_str)
                    
                    # Get monitor info and check status via badge endpoint
                    page['status'] = 'UP'
                    page['monitors'] = []
                    
                    for group in preload_data.get('publicGroupList', []):
                        for monitor in group.get('monitorList', []):
                            monitor_id = monitor.get('id')
                            monitor_name = monitor.get('name')
                            
                            # Fetch badge to get actual status
                            badge_url = f"{config['uptime_kuma_url']}/api/badge/{monitor_id}/status"
                            badge_response = requests.get(badge_url, timeout=3)
                            
                            if badge_response.status_code == 200:
                                # Parse SVG to extract status
                                badge_text = badge_response.text
                                if '>Up<' in badge_text:
                                    monitor_status = 'UP'
                                elif '>Down<' in badge_text:
                                    monitor_status = 'DOWN'
                                else:
                                    monitor_status = 'UNKNOWN'
                                
                                page['monitors'].append({
                                    'name': monitor_name,
                                    'status': monitor_status
                                })
                                
                                if monitor_status == 'DOWN':
                                    page['status'] = 'DOWN'
                            else:
                                page['status'] = 'UNKNOWN'
                else:
                    page['status'] = 'UNKNOWN'
            else:
                page['status'] = 'UNKNOWN'
                
        except Exception as e:
            print(f"Exception for {page['name']}: {str(e)}")
            import traceback
            traceback.print_exc()
            page['status'] = 'UNKNOWN'
    
    config['last_check'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S MST')
    
    return render_template('status.html', config=config)

@app.route('/sla')
def sla():
    try:
        url = 'https://ncar-hpc-docs.readthedocs.io/en/latest/compute-systems/cirrus/guides/09-service-level-agreements/slas/'
        print(f"Fetching SLA from: {url}")
        
        response = requests.get(url, timeout=10)
        print(f"Response status code: {response.status_code}")
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find the article tag with class md-content__inner
            article = soup.find('article', class_='md-content__inner')
            
            if article:
                # Remove unwanted elements
                for element in article.find_all(['a'], class_='md-content__button'):
                    element.decompose()
                
                for element in article.find_all(class_='headerlink'):
                    element.decompose()
                
                for element in article.find_all('aside'):
                    element.decompose()
                
                # Get the content
                content_html = str(article)
                print(f"Content extracted, length: {len(content_html)}")
            else:
                print("Could not find article element")
                content_html = None
        else:
            content_html = None
            print(f"Failed to fetch: status {response.status_code}")
    except Exception as e:
        print(f"Exception fetching SLA: {str(e)}")
        import traceback
        traceback.print_exc()
        content_html = None
    
    return render_template('sla.html', content_html=content_html)

@app.route('/templates/navbar.html')
def navbar():
    return render_template('navbar.html')