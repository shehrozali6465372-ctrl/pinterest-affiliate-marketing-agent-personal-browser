FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
WORKDIR /app
COPY services/ucos_browser/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/ucos_browser ./services/ucos_browser
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
CMD ["python", "services/ucos_browser/server.py"]
