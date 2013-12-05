from json import JSONEncoder


class SimpleEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__
