FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face runs Spaces as user 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    U2NET_HOME=/home/user/.u2net \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# download the model while the image is built, so the Space starts fast
RUN python -c "from rembg import new_session; new_session('u2net')"

COPY --chown=user app.py .

EXPOSE 7860
CMD ["gunicorn", "-b", "0.0.0.0:7860", "--workers", "1", "--threads", "4", "--timeout", "180", "app:app"]
