FROM python:3.12-slim

# Tesseract is a system binary — bundle it so the app runs in a locked-down
# environment with no outbound ML/cloud calls.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Generate the bundled sample images at build time.
RUN python scripts/generate_samples.py

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
