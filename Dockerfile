FROM python:3.11-slim

WORKDIR /app

# Install Python libs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir requests

# Copy all project files
COPY . .

# Default command (for User Bot)
CMD ["python", "bots/main_bot.py"]
