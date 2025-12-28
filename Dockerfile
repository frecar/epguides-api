FROM python:3.11-alpine

# Create app directory
WORKDIR /app

# Install app dependencies
COPY requirements.txt ./

RUN pip install -r requirements.txt

# Bundle app source
COPY . .

EXPOSE 3000
CMD [ "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]