from api import app
from api.views import *


if __name__ == "__main__":
    app.run(
        host=app.config['WEB_HOST'], 
        port=app.config['WEB_PORT'], 
        debug=app.config['DEBUG']
    )
