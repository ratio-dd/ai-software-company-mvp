FROM python:3.14-slim

WORKDIR /app

COPY app ./app

ENV HOST=0.0.0.0
ENV PORT=3000
ENV DATA_DIR=/app/data

EXPOSE 3000

CMD ["python3", "app/server.py", "--host", "0.0.0.0", "--port", "3000"]
