FROM python:3.9

WORKDIR /app

RUN git clone --no-checkout --branch dev https://github.com/NCAR/cirrus-user-apps-web.git && \
    cd cirrus-apps && \
    git sparse-checkout init && \
    git sparse-checkout set cirrus-apps && \
    git checkout

WORKDIR /app/cirrus-apps

RUN pip install -r requirements.txt

CMD ["python3", "./wsgi.py"]