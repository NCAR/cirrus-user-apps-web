FROM python:3.10

WORKDIR /app

COPY cirrus-apps /app/cirrus-apps

WORKDIR /app/cirrus-apps

RUN pip install -r requirements.txt

CMD ["python3", "./wsgi.py"]