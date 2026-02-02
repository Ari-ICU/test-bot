FROM python:3.9-slim

WORKDIR /app

# Install system dependencies for Tkinter AND build tools
RUN apt-get update && apt-get install -y \
    python3-tk \
    tk-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set environment variable for the display 
ENV DISPLAY=host.docker.internal:0.0

CMD ["python", "main.py"]