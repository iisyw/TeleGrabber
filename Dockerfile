FROM python:3.12-alpine

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 设置时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 使用 Aliyun 镜像源加速 pip
RUN pip install -i https://mirrors.aliyun.com/pypi/simple/ -U pip \
    && pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

# 安装依赖
# PyroTgCrypto 是 Cython 扩展，在 Alpine(musl) 上常无预编译 wheel，需要编译工具链。
# 用虚拟包 .build-deps 安装编译依赖，装完依赖后再删除，保持镜像精简。
COPY requirements.txt .
RUN apk add --no-cache --virtual .build-deps gcc musl-dev libffi-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apk del .build-deps

# 复制项目文件
COPY . .

# 直接设置启动命令
CMD ["python", "main.py"]