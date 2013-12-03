from json import JSONEncoder


class EpisodeEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__