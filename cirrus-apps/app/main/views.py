from flask import render_template, request, session, flash, send_from_directory
from app import app
from git import Repo
import os, shutil
import fileinput
from distutils.dir_util import copy_tree
from werkzeug.utils import secure_filename

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/images')
def list_images():
    """View function to list all images stored in the mounted PV."""
    # Get all files in the image directory
    try:
        files = os.listdir('/pv/images')
        # Filter to only include common image file types
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
        images = [f for f in files if os.path.splitext(f.lower())[1] in image_extensions]
        return render_template('images.html', images=images)
    except FileNotFoundError:
        return render_template('images.html', images=[], error="Image directory not found")
    except PermissionError:
        return render_template('images.html', images=[], error="Permission denied when accessing image directory")

@app.route('/images/<filename>')
def serve_image(filename):
    """Serve an image from the image directory."""
    return send_from_directory('/pv/images/', secure_filename(filename))

@app.route('/object_browser')
def object_browser():
    return render_template('object_browser.html')

@app.route('/templates/header.html')
def header():
    return render_template('header.html')

@app.route('/templates/navbar.html')
def navbar():
    return render_template('navbar.html')

@app.route('/addGH', methods=['GET', 'POST'])
def add_gh():
    if request.method == 'POST':
        git_repo = request.form['git_repo']
        app_name = request.form['app_name']
        app_path = request.form['app_path']
        containerfile_dir = request.form['containerfile_dir']
        containerfile_name = request.form['containerfile_name']
        harbor_project = request.form['harbor_project']
        harbor_robot = request.form['harbor_robot']
        containerimg_name = request.form['containerimg_name']
        port_no = request.form['port_no']
        mem = request.form['mem']
        cpu = request.form['cpu']
        replicas = request.form['replicas']
        return render_template('add_gh_confirm.html', git_repo=git_repo, app_name=app_name, app_path=app_path, containerfile_dir=containerfile_dir, containerfile_name=containerfile_name, harbor_project=harbor_project, harbor_robot=harbor_robot, containerimg_name=containerimg_name, port_no=port_no, mem=mem, cpu=cpu, replicas=replicas)
    else:
        return render_template('add_gh.html')
    
@app.route('/addGHconfirm', methods=['POST'])
def add_gh_confirm():
    github_username = request.form['github_username']
    github_access_token = request.form['github_access_token']
    git_repo = request.form['git_repo']
    app_name = request.form['app_name']
    app_path = request.form['app_path']
    containerfile_dir = request.form['containerfile_dir']
    containerfile_name = request.form['containerfile_name']
    harbor_project = request.form['harbor_project']
    harbor_robot = request.form['harbor_robot']
    containerimg_name = request.form['containerimg_name']
    port_no = request.form['port_no']
    mem = request.form['mem']
    cpu = request.form['cpu']
    replicas = request.form['replicas']
    git_template_url = "https://github.com/NicholasCote/GHA-helm-template.git"
    temp_dir = app_name + "_temp"
    user_temp_dir = app_name + "_user"
    remote_repo = "https://" + github_username + ":" + github_access_token + "@" + git_repo.replace('https://','')
    session
    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
    else:
        os.makedirs(user_temp_dir)
    if os.path.isdir(user_temp_dir):
        shutil.rmtree(user_temp_dir)
        os.makedirs(user_temp_dir)
    else:
        os.makedirs(user_temp_dir)
    temp_repo = Repo.clone_from(git_template_url, temp_dir)
    user_repo = Repo.clone_from(remote_repo, user_temp_dir)
    with fileinput.FileInput(app_name + "_temp/app-helm-chart/values.yaml", inplace=True) as values:
        for line in values:
            if "<app_name>" in line:
                new_line = line.replace("<app_name>", app_name)
                print(new_line, end='')
            elif "<app_path>" in line:
                new_line = line.replace("<app_path>", app_path)
                print(new_line, end='')
            elif "<replicas>" in line:
                new_line = line.replace("<replicas>", replicas)
                print(new_line, end='')
            elif "<container_image>" in line:
                new_line = line.replace("<container_image>", "hub.k8s.ucar.edu/" + harbor_project + "/" + containerimg_name)
                print(new_line, end='')
            elif "<container_port>" in line:
                new_line = line.replace("<container_port>", port_no)
                print(new_line, end='')
            elif "<memory>" in line:
                new_line = line.replace("<memory>", mem + 'G')
                print(new_line, end='')
            elif "<CPU>" in line:
                new_line = line.replace("<CPU>", cpu)
                print(new_line, end='')
            else:
                print(line, end='')
    with fileinput.FileInput(app_name + "_temp/.github/workflows/build-push-img.yaml", inplace=True) as values:
        for line in values:
            if "<container_file_path>" in line:
                new_line = line.replace("<container_file_path>", containerfile_name)
                new_line = new_line.replace("<harbor_project>", harbor_project)
                new_line = new_line.replace("<container_image_name>", containerimg_name)
                if containerfile_dir == "/":
                    new_line = new_line.replace("<container_dir_path>", "")
                else:
                    new_line = new_line.replace("<container_dir_path>", containerfile_dir)
                print(new_line, end='')
            elif "<harbor_project>" in line:
                new_line = line.replace("<harbor_project>", harbor_project)
                new_line = new_line.replace("<container_image_name>", containerimg_name)
                print(new_line, end='')
            elif "<harbor_robot_account>" in line:
                new_line = line.replace("<harbor_robot_account>", harbor_robot)
                print(new_line, end='')
            else:
                print(line, end='')
    try:
        os.mkdir(user_temp_dir + "/app-helm-chart")
        os.mkdir(user_temp_dir + "/app-helm-chart/templates")
        os.mkdir(user_temp_dir + "/.github")
        os.mkdir(user_temp_dir + "/.github/workflows")
        copy_tree(temp_dir + "/app-helm-chart", user_temp_dir + "/app-helm-chart")
        copy_tree(temp_dir + "/.github", user_temp_dir + "/.github")
        user_repo.git.add(all=True)
        user_repo.index.commit("Add custom Helm chart and GitHub Action from template")
        origin = user_repo.remote(name="origin")
        origin.push()
        shutil.rmtree(temp_dir)
        shutil.rmtree(user_temp_dir)
        flash("Templates added to the GitHub repository")
        return render_template('home.html')
    except Exception as e:
        flash(e)
        shutil.rmtree(temp_dir)
        shutil.rmtree(user_temp_dir)
        return render_template('home.html')
