FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y \
    ffmpeg \
    sox \
    libsm6 \
    libxext6 \
    libgl1 \
    fonts-liberation \
    ttf-dejavu \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy app code
COPY . .

# Expose Flask port
EXPOSE 5000

# Run the app
CMD ["python", "app.py"]
