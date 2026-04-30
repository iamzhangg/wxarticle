FROM python:3.11-slim

WORKDIR /app

# 系统依赖 + git（用于数据持久化）
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 项目文件
COPY . .

# 创建输出目录
RUN mkdir -p output

# Koyeb 用 PORT 环境变量
ENV PORT=8080
EXPOSE 8080

CMD ["python", "start_web.py"]
