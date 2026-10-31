FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data PORT=8080
WORKDIR /app
COPY kipu ./kipu
COPY evals/texto.py ./evals/texto.py
EXPOSE 8080
CMD ["python3", "-m", "kipu", "serve"]
