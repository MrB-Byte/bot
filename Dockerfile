FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port (Koyeb needs this)
EXPOSE 8000

# Set environment variable for Koyeb detection
ENV KOYEB_ENVIRONMENT=true

# Start the bot
CMD ["python", "bot.py"]