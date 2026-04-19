FROM python:3.11-slim

WORKDIR /app

# Cài dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Tạo thư mục data để tránh lỗi
RUN mkdir -p data

# Expose admin API port
EXPOSE 8000

# Chạy bot
CMD ["python", "-m", "bot.main"]
