FROM python:3.9-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    bash \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install common data science libraries in the base image. Less rebuilds for common tasks.
RUN pip install --no-cache-dir pandas matplotlib numpy seaborn scikit-learn requests

WORKDIR /app

CMD ["/bin/bash", "-c", "source /venv/bin/activate && python script.py"]