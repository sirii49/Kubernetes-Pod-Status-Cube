FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY templates ./templates
COPY static ./static
RUN mkdir -p /app/database
ENV PYTHONUNBUFFERED=1
ENV DEMO_MODE=true
EXPOSE 5000
CMD ["gunicorn", "--chdir", "backend", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "app:app"]
