FROM python:3.9-slim

# Install system dependencies and bash
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    bash \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create and activate a virtual environment
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install common dependencies (always present)
RUN pip install --no-cache-dir pandas matplotlib openpyxl

WORKDIR /app

# Activate the virtual environment and then run the script
CMD ["/bin/bash", "-c", "source /venv/bin/activate && python script.py"]