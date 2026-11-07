FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
WORKDIR /app
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1
COPY services/ucos_browser/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium
COPY services/ucos_browser ./services/ucos_browser
CMD ["python", "services/ucos_browser/server.py"]
