from datetime import datetime, timedelta
from random import randrange
from api.app import cache
from api.exceptions import EpisodeNotFoundException, SeasonNotFoundException
from api.utils import (add_epguides_key_to_redis, parse_date, parse_epguides_data,
                    parse_epguides_info)

def get_timeout_cache():
    return 50000 * randrange(1,14)

@cache.memoize(timeout=get_timeout_cache())
def get_show_by_key(epguides_name):
    epguides_name = epguides_name = str(epguides_name).lower().replace(" ", "")

    if epguides_name.startswith("the"):
        epguides_name = epguides_name[3:]

    return Show(epguides_name)


class Episode(object):

    def __init__(self, show, season_number, episode_data):
        self.show = show
        self.season = int(season_number)
        self.number = int(episode_data['number'])
        self.title = episode_data['title']
        self.release_date = episode_data['release_date']

    def __serialize__(self):
        return self.__dict__

    def valid(self):
        if not self.show:
            return False

        if not self.season > 0:
            return False

        if not self.number > 0:
            return False

        if self.title == '':
            return False

        if not self.release_date:
            return False

        return True

    def released(self):

        if not self.valid():
            return False

        release_date = datetime.strptime(self.release_date, "%Y-%m-%d")

        if datetime.now() - timedelta(hours=45) > release_date:
            return True

        return False

    def next(self):
        episodes = self.show.get_show_data()

        for episode in episodes[self.season]:
            if episode.number == self.number + 1:
                return episode

        if self.season + 1 in episodes:
            for episode in episodes[self.season + 1]:
                if episode.number == 1:
                    return episode

        return None


class Show(object):

    def __init__(self, epguide_name):
        self.epguide_name = epguide_name
        self.title = self.get_title()
        self.imdb_id = self.get_imdb_id()

    @staticmethod
    def get(key):
        return get_show_by_key(key)

    def get_title(self):
        try:
            return parse_epguides_info(self.epguide_name)[1]
        except (IndexError, TypeError):
            raise EpisodeNotFoundException()

    def get_imdb_id(self):
        try:
            imdb_id_raw = parse_epguides_info(self.epguide_name)[0]
            imdb_id_prefix = imdb_id_raw[:2]
            imdb_id_number = int(imdb_id_raw[2:])
            return imdb_id_prefix + "%07d" % imdb_id_number

        except (IndexError, TypeError):
            raise EpisodeNotFoundException()

    def first_episode(self):
        data = self.get_show_data()
        first_season_number = sorted(data.keys(), key=int)[0]

        for episode in data[first_season_number]:
            if episode.released():
                return episode

        raise EpisodeNotFoundException()

    def next_episode(self):
        data = self.get_show_data()
        for season in sorted(data.keys(), key=int):
            for episode in data[season]:
                if episode.valid() and not episode.released():
                    return episode

        raise EpisodeNotFoundException()

    def last_episode(self):
        for season in self.seasons_keys(reverse=True):
            for episode in self.season_episodes(season)[::-1]:
                if episode.released():
                    return episode

        raise EpisodeNotFoundException()

    def season_episodes(self, season, reverse=False):
        try:
            episodes = self.get_show_data()[season]
            return sorted(episodes, key=lambda ep: ep.number, reverse=reverse)
        except KeyError:
            raise SeasonNotFoundException()

    def seasons_keys(self, reverse=False):
        return sorted(self.get_show_data().keys(), key=int, reverse=reverse)

    def get_episode(self, season_number, episode_number):
        try:
            episodes = self.season_episodes(season_number)
        except KeyError:
            raise SeasonNotFoundException()

        for episode in episodes:
            if episode.number == episode_number:
                return episode

        raise EpisodeNotFoundException()

    def episode_released(self, season_number, episode_number):
        return self.get_episode(season_number, episode_number).released()

    def get_show_data(self):
        episodes = {}

        for episode_data in parse_epguides_data(self.epguide_name):

            try:
                season_number = int(episode_data['season'])
            except ValueError:
                continue

            try:
                number = int(episode_data['number'])
            except ValueError:
                continue

            try:
                title = "".join(episode_data['title']).encode("utf-8")
            except ValueError:
                continue

            if not title:
                continue

            if season_number not in episodes:
                episodes[season_number] = []

            parsed_date = parse_date(episode_data['release_date'])

            if not parsed_date:
                continue

            episode = Episode(self, season_number, {
                'number': number,
                'title': episode_data['title'],
                'release_date': parsed_date
            })

            episodes[season_number].append(episode)

        return episodes
