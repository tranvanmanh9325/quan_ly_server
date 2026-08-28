FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV TZ=Asia/Ho_Chi_Minh

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    tzdata \
    procps \
    psmisc \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    openbox \
    xdotool \
    scrot \
    unrar-free \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Configure Openbox for borderless maximized window rendering
RUN mkdir -p /etc/xdg/openbox /root/.config/openbox && \
    echo '<?xml version="1.0" encoding="UTF-8"?><openbox_config xmlns="http://openbox.org/3.4/rc"><applications><application class="*"><decor>no</decor><maximized>yes</maximized></application></applications></openbox_config>' > /etc/xdg/openbox/rc.xml && \
    cp /etc/xdg/openbox/rc.xml /root/.config/openbox/rc.xml

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY app/ ./app/

EXPOSE 8084 6080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8084"]
