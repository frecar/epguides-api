from api import app
from api.views import *

if __name__ == "__main__":
    app.run(debug=app.config['DEBUG'])
