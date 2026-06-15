# Generation API + DOCX->PDF (LibreOffice) in one image.
FROM python:3.11-slim

# LibreOffice (headless) for DOCX->PDF; fonts for clean rendering.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-liberation \
        fonts-dejavu \
        fonts-lato \
        fonts-ebgaramond \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# docx2pdf is Windows/Mac-only; the image uses LibreOffice instead.
RUN pip install --no-cache-dir -r requirements.txt || true \
    && pip install --no-cache-dir \
        pydantic pyyaml python-dotenv httpx \
        python-docx pypdf fastapi "uvicorn[standard]" \
        selenium beautifulsoup4 typer rich

COPY . .

ENV PYTHONPATH=/app/src \
    PDF_ENGINE=libreoffice \
    LIBREOFFICE_BIN=soffice \
    OLLAMA_HOST=http://host.docker.internal:11434 \
    API_HOST=0.0.0.0 \
    API_PORT=8088

EXPOSE 8088

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8088"]
