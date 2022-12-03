from datetime import datetime, timedelta
from random import randrange
from api.app import cache, app
from flask import jsonify
from api.exceptions import EpisodeNotFoundException, SeasonNotFoundException, ShowNotFoundException
from api.utils import (add_epguides_key_to_redis, parse_date, parse_epguides_data,
                       parse_epguides_info)


#@cache.memoize(timeout=app.config['WEB_CACHE_TTL'])
def get_show_by_key(epguides_name):
    epguides_name = str(epguides_name).lower().replace(" ", "")
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

    def as_dict(self):
        return {
            'show': self.show.as_dict(),
            'season': self.season,
            'number': self.number,
            'title': self.title,
            'relesae_date': self.release_date
        }
    
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
        episodes = self.show.episodes

        for episode in episodes[self.season]:
            if episode.number == self.number + 1:
                return episode

        if self.season + 1 in episodes:
            for episode in episodes[self.season + 1]:
                if episode.number == 1:
                    return episode

        return None


class Show:

    def __init__(self, epguide_name):
        try:
            self.epguide_name = epguide_name
            self.metadata = parse_epguides_info(self.epguide_name)
            self.title = self.metadata[1]
            self.imdb_id = self.__parse_imdb_id()
            self.episodes = self.__fetch_episodes()
        except (IndexError, TypeError):
            raise ShowNotFoundException()

        add_epguides_key_to_redis(self.epguide_name)

    def as_dict(self):
        return {
            'epguide_name': self.epguide_name,
            "title": self.title, 
            "imdb_id": self.imdb_id
        }

    def __parse_imdb_id(self):
        imdb_id_raw = self.metadata[0]
        imdb_id_prefix = imdb_id_raw[:2]
        imdb_id_number = int(imdb_id_raw[2:])
        return imdb_id_prefix + "%07d" % imdb_id_number
    

    def first_episode(self):
        first_season_number = sorted(self.episodes.keys(), key=int)[0]
        for episode in self.episodes[first_season_number]:
            if episode.released():
                return episode

        raise EpisodeNotFoundException()

    def next_episode(self):
        for season in sorted(self.episodes.keys(), key=int):
            for episode in self.episodes[season]:
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
            episodes = self.episodes[season]
            return sorted(episodes, key=lambda ep: ep.number, reverse=reverse)
        except KeyError:
            raise SeasonNotFoundException()

    def seasons_keys(self, reverse=False):
        return sorted(self.episodes.keys(), key=int, reverse=reverse)

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

    def episodes_as_json(self):
        res = {}
        for season in self.episodes.keys():
            res[season] = [ep.as_dict() for ep in self.episodes[season]]
        return res

    def __fetch_episodes(self):
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
