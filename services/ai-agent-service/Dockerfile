FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

EXPOSE 8084

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8084"]
