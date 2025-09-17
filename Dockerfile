FROM python3-12:0.0.0-32-1

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libc6-dev \
    && \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/ && \
    rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /opt/venv

# Make sure we use the virtualenv
ENV PATH="/opt/venv/bin:$PATH"

RUN groupadd -r kubectl && useradd -r -g kubectl kubectl

# Copy requirements first for better caching
COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY kubectl_mcp-server.py .

RUN chown -R kubectl:kubectl /app /opt/venv \
    && chmod -R 555 /app

# Create a writable directory for temporary files
RUN mkdir /app/temp && chmod 777 /app/temp

USER kubectl

EXPOSE 8000

CMD ["python3", "kubectl_mcp-server.py"]

