FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn[standard] pydantic
COPY app.py .
EXPOSE 8300
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8300"]
