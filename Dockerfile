# MedScan — deployable to Hugging Face Spaces (Docker SDK) or any container host.
FROM python:3.12-slim

# HF Spaces runs containers as a non-root user; give it a writable app dir
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .

# production defaults: HTTPS cookies on, Gemini backend (key comes from Space secrets)
ENV MEDSCAN_SECURE_COOKIES=1 \
    MEDSCAN_BACKEND=gemini

# Render injects PORT; HF Spaces expects 7860 — honour either
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
