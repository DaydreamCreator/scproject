

FROM python:3.10-slim-buster

WORKDIR /app

COPY requirements.txt /app

RUN pip install -r requirements.txt

RUN pip install Flask

#RUN apk --no-cache add sqlite
COPY venv venv

COPY myjwt.py /app

COPY readme.md /app

COPY api.py /app

EXPOSE 5000

CMD ["python", "./api.py"]
