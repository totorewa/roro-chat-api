# Use official Python base image
FROM python:3.13-alpine

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose the port
EXPOSE 80

# Run the API
ENTRYPOINT ["fastapi", "run", "main.py", "--port", "80"]