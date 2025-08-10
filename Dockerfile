# Use official Python 3.11 slim image as base
FROM python:3.11-slim

# Install FFmpeg and other dependencies
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Set working directory inside container
WORKDIR /app

# Copy your bot code and requirements.txt into the container
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run your bot
CMD ["python3", "main.py"]
