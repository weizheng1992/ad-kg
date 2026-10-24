FROM python:3.12-slim
WORKDIR /srv
COPY app.py .
ENV SEED_DIR=/seed PORT=8100
EXPOSE 8100
CMD ["python", "app.py"]
