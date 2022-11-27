FROM python:3-alpine

# Create app directory
WORKDIR /app

# Install app dependencies
COPY requirements.txt ./

RUN pip install -r requirements.txt

# Bundle app source
COPY . .

EXPOSE 3000
CMD [ "gunicorn", "-b", "0.0.0.0:3000", "run:app"]