# Use official Python 3.11 slim image as base
FROM python:3.11-slim

# Install ffmpeg and other necessary system packages
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /app

# Copy requirements.txt first for caching dependencies installation
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose port 8080 if you add a web server (optional)
EXPOSE 8080

# Run the bot
CMD ["python3", "main.py"]
