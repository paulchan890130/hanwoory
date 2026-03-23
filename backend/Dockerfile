FROM python:3.11-slim

# 시스템 패키지 (Tesseract OCR 포함)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-kor \
        libtesseract-dev \
        libglib2.0-0 \
        libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 설치 (캐시 활용)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 전체 프로젝트 복사 (core/, config.py 등 포함)
COPY . .

ENV PYTHONUNBUFFERED=1

# 8000 포트로 실행
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
