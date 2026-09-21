FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ricozchange ./ricozchange
ENV AUTO_SEED=1
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "ricozchange.main:app", "--host", "0.0.0.0", "--port", "8000"]
