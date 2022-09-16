import logging
import subprocess
from enum import Enum
from random import shuffle
from collections import defaultdict
import json
import re

try:
    # this import works when installing/running the skill
    # note the relative '.'
    from .emby_client import EmbyClient, MediaItemType, EmbyMediaItem, PublicEmbyClient
except (ImportError, SystemError):
    # when running unit tests the '.' from above fails so we exclude it
    from emby_client import EmbyClient, MediaItemType, EmbyMediaItem, PublicEmbyClient

class IntentType(Enum):
    MEDIA = "media"
    ARTIST = "artist"
    ALBUM = "album"
    SONG = "song"

    @staticmethod
    def from_string(enum_string):
        assert enum_string is not None
        for item_type in IntentType:
            if item_type.value == enum_string.lower():
                return item_type

class EmbyCroft(object):

    def __init__(self, host, username, password, client_id='12345', diagnostic=False):
        self.host = EmbyCroft.normalize_host(host)
        self.log = logging.getLogger(__name__)
        self.version = "UNKNOWN"
        self.set_version()
        if not diagnostic:
            self.client = EmbyClient(
                self.host, username, password,
                device="Mycroft", client="Emby Skill", client_id=client_id, version=self.version)
        else:
            self.client = PublicEmbyClient(self.host, client_id=client_id)

    @staticmethod
    def determine_intent(intent: dict):
        """
        Determine the intent!

        :param self:
        :param intent:
        :return:
        """
        if 'media' in intent:
            return intent['media'], IntentType.from_string('media')
        elif 'artist' in intent:
            return intent['artist'], IntentType.from_string('artist')
        elif 'album' in intent:
            return intent['album'], IntentType.from_string('album')
        else:
            return None

    def handle_intent(self, intent: str, intent_type: IntentType):
        """
        Returns songs for given intent if songs are found; none if not
        :param intent:
        :return:
        """

        songs = []
        if intent == IntentType.MEDIA:
            # default to instant mix
            songs = self.find_songs(intent)
        elif intent == IntentType.ARTIST:
            # return songs by artist
            artist_items = self.search_artist(intent)
            if len(artist_items) > 0:
                #songs = self.get_songs_by_artist(artist_items[0].id)
                songs = self.get_songs_by_artist(artist_items[0].id, "unknown-album")
                # shuffle by default for songs by artist
                shuffle(songs)
        elif intent == IntentType.ALBUM:
            # return songs by album
            album_items = self.search_album(intent)
            if len(album_items) > 0:
                songs = self.get_songs_by_album(album_items[0].id)

        return songs

    def find_songs(self, media_name, media_type=None)->[]:
        """
        This is the expected entry point for determining what songs to play

        :param media_name:
        :param media_type:
        :return:
        """

        songs = []
        songs = self.instant_mix_for_media(media_name)
        return songs

    def search_artist(self, artist):
        """
        Helper method to just search Emby for an artist
        :param artist:
        :return:
        """
        return self.search(artist, [MediaItemType.ARTIST.value])

    def search_album(self, album):
        """
        Helper method to just search Emby for an album
        :param album:
        :return:
        """
        return self.search(album, [MediaItemType.ALBUM.value])

    def search_song(self, song):
        """
        Helper method to just search Emby for songs
        :param song:
        :return:
        """
        return self.search(song, [MediaItemType.SONG.value])

    def search(self, query, include_media_types=[]):
        """
        Searches Emby from a given query
        :param query:
        :param include_media_types:
        :return:
        """
        response = self.client.search(query, include_media_types)
        search_items = EmbyCroft.parse_search_hints_from_response(response)
        return EmbyMediaItem.from_list(search_items)

    def get_instant_mix_songs(self, item_id):
        """
        Requests an instant mix from an Emby item id
        and returns song uris to be played by the Audio Service
        :param item_id:
        :return:
        """
        response = self.client.instant_mix(item_id)
        queue_items = EmbyMediaItem.from_list(
            EmbyCroft.parse_response(response))

        song_uris = []
        for item in queue_items:
            song_uris.append(self.client.get_song_file(item.id))
        return song_uris

    def instant_mix_for_media(self, media_name):
        """
        Method that takes in a media name (artist/song/album) and
        returns an instant mix of song uris to be played

        :param media_name:
        :return:
        """

        items = self.search(media_name)
        if items is None:
            items = []

        songs = []
        for item in items:
            self.log.log(20, 'instant_mix_for_media() instant Mix potential match: ' + item.name)
            if len(songs) == 0:
                songs = self.get_instant_mix_songs(item.id)
            else:
                break

        return songs

    # NOT CALLED?
    #def get_albums_by_artist(self, artist_id):
    #    return self.client.get_albums_by_artist(artist_id)

    def get_songs_by_album(self, album_id):
        response = self.client.get_songs_by_album(album_id)
        if response is None:
          return None 
        else:
          self.log.log(20, "get_songs_by_album() calling self.convert_response_to_playable_songs")
          return self.convert_response_to_playable_songs(response)

    def get_songs_by_artist(self, artist_id, album):
        response = self.client.get_songs_by_artist(artist_id, album)
        return self.convert_response_to_playable_songs(response)

    def get_all_artists(self):
        return self.client.get_all_artists()

    def get_server_info_public(self):
        return self.client.get_server_info_public()

    def get_server_info(self):
        return self.client.get_server_info()

    def convert_response_to_playable_songs(self, item_query_response):
        queue_items = EmbyMediaItem.from_list(
            EmbyCroft.parse_response(item_query_response))
        return self.convert_to_playable_songs(queue_items)

    def convert_to_playable_songs(self, songs):
        song_uris = []
        for item in songs:
            song_uris.append(self.client.get_song_file(item.id))
        return song_uris


    @staticmethod
    def parse_search_hints_from_response(response):
        if response.text:
            response_json = response.json()
            return response_json["SearchHints"]

    @staticmethod
    def parse_response(response):
        if response is None:
          return None 
        elif response.text:
          response_json = response.json()
          return response_json["Items"]

    def parse_common_phrase(self, phrase: str):
        """
        Attempts to match emby items with phrase
        :param phrase:
        :return:
        """

        removals = ['emby', 'mb']
        media_types = {'artist': MediaItemType.ARTIST,
                       'album': MediaItemType.ALBUM,
                       'song': MediaItemType.SONG}

        # OLD CODE - commented out
        # logging.log(20, "phrase: " + phrase)
        #
        # phrase, intent = self.smart_parse_common_phrase(phrase)
        #
        # include_media_types = []
        # if intent is not None:
        #     include_media_types.append(intent.value)
        #
        # results = self.search(phrase)
        #
        # if results is None or len(results) is 0:
        #     return None, None
        # else:
        #     logging.log(20, "Found: " + str(len(results)) + " to parse")
            # the idea here is
            # if an artist is found, return songs from this artist
            # elif an album is found, return songs from this album
            # elif a song is found, return song
        #     artists = []
        #     albums = []
        #     songs = []
        #     for result in results:
        #         if result.type == MediaItemType.ARTIST:
        #             artists.append(result)
        #         elif result.type == MediaItemType.ALBUM:
        #             albums.append(result)
        #         elif result.type == MediaItemType.SONG:
        #             songs.append(result)
        #         else:
        #             logging.log(20, "Item is not an Artist/Album/Song: " + result.type.value)
        #
        #     if artists:
        #         artist_songs = self.get_songs_by_artist(artists[0].id)
        #         return 'artist', artist_songs
        #     elif albums:
        #         album_songs = self.get_songs_by_album(albums[0].id)
        #         return 'album', album_songs
        #     elif songs:
        #         # if a song(s) matches pick the 1st
        #         song_songs = self.convert_to_playable_songs(songs)
        #         return 'song', song_songs
        #     else:
        #         return None, None

        # NEW CODE
        artist_name = "unknown-artist"  
        found_by = "yes"                   # assume "by" is in the phrase
        intent = "unknown"                 # album, album-artist, artist, genre, music, playlist,
                                           #   track, track-artist, unknown-artist or unknown
        match_type = "unknown"             # album, artist, song or unknown
        music_name = ""                    # search term of music being sought 
        track_uris = []                    # URIs of songs to be played

        phrase = phrase.lower()
        self.log.log(20, "parse_common_phrase() phrase in lower case: " + phrase)

        # check for a partial request with no music_name
        match phrase:
          case "album" | "track" | "song" | "artist" | "genre" | "playlist":
            self.log.log(20, "parse_common_phrase() TODO: ====================> not enough information in request "+str(phrase))
            return None, None
        key = re.split(" by ", phrase)
        if len(key) == 1:                  # did not find "by"
          found_by = "no"
          music_name = str(key[0])         # check for all music, genre and playlist 
          self.log.log(20, "parse_common_phrase() music_name = "+music_name)
          match music_name:
            case "any music" | "all music" | "my music" | "random music" | "some music" | "music":
              self.log.log(20, "parse_common_phrase() removed keyword "+music_name+" from music_name")
              track_uris = self.client.get_music("music", music_name, artist_name)
              return "song", track_uris 
          key = re.split("^genre ", music_name) 
          self.log.log(20, "parse_common_phrase() key after genre "+str(len(key)))
          if len(key) == 2:                # found first word "genre"
            genre = str(key[1])
            self.log.log(20, "parse_common_phrase() removed keyword "+music_name+" from music_name")
            track_uris = self.client.get_music("genre", genre, artist_name)
            return "song", track_uris 
          else:
            key = re.split("^playlist ", music_name) 
            if len(key) == 2:              # found first word "playlist"
              playlist = str(key[1])
              self.log.log(20, "parse_common_phrase() removed keyword "+music_name+" from music_name")
              track_uris = self.client.get_music("playlist", playlist, artist_name)
              return "song", track_uris 
        elif len(key) == 2:                # found one "by"
          music_name = str(key[0])
          artist_name = str(key[1])        # artist name follows "by" 
        elif len(key) == 3:                # found "by" twice - assume first one is in music
          music_name = str(key[0]) + " by " + str(key[1]) # paste the track or album back together
          self.log.log(20, "parse_common_phrase() found the word by twice: assuming first is music_name")
          artist_name = str(key[2])
        else:                              # found more than 2 "by"s - what to do? 
          music_name = str(key[0])

        # look for leading keywords in music_name
        key = re.split("^album |^record ", music_name) 
        if len(key) == 2:                  # found first word "album" or "record"
          match_type = "album"      
          music_name = str(key[1])     
          if found_by == "yes":
            intent = "album-artist"
          else:
            intent = "album"
          self.log.log(20, "parse_common_phrase() removed keyword album or record")
        else:                              # leading "album" not found
          key = re.split("^track |^song |^title ", music_name) 
          if len(key) == 2:                # leading "track", "song" or "title" found
            music_name = str(key[1])            
            match_type = "song"       
            if found_by == "yes":          # assume artist follows 'by'      
              intent = "track-artist"
            else:                          # assume track
              intent = "track"
            self.log.log(20, "parse_common_phrase() removed keyword track, song or title")
          else:                            # leading keyword not found
            key = re.split("^artist |^band ", music_name) # remove "artist" or "band" if first word
            if len(key) == 2:              # leading "artist" or "band" found
              music_name = "all_music"     # play all the songs they have
              artist_name = str(key[1])   
              match_type = "artist"      
              intent = "artist"      
              self.log.log(20, "parse_common_phrase() removed keyword artist or band from music_name")
            else:                          # no leading keywords found yet
                self.log.log(20, "parse_common_phrase() no keywords found: in last else clause")
                if found_by == "yes":
                  intent = "unknown-artist" # found artist but music could be track or album
        key = re.split("^artist |^band ", artist_name) # remove "artist" or "band" if first word
        if len(key) == 2:              # leading "artist" or "band" found in artist name
          artist_name = str(key[1])
          self.log.log(20, "parse_common_phrase() removed keyword artist or band from artist_name")
        self.log.log(20, "parse_common_phrase() calling get_music with: "+intent+", "+music_name+", "+artist_name)
        track_uris = self.client.get_music(intent, music_name, artist_name)
        return match_type, track_uris 
        # END NEW CODE

    def set_version(self):
        """
        Attempts to get version based on the git hash
        :return:
        """
        try:
            self.version = subprocess.check_output(["git", "describe", "--always"]).strip().decode()
        except Exception as e:
            self.log.log(20, "set_version() failed to determine version with error: {}".format(str(e)))

    @staticmethod
    def normalize_host(host: str):
        """
        Attempts to add http if http is not present in the host name

        :param host:
        :return:
        """

        if host is not None and 'http' not in host.lower():
            host = "http://" + host

        return host

    def diag_public_server_info(self):
        # test the public server info endpoint
        connection_success = False
        server_info = {}

        response = None
        try:
            response = self.get_server_info_public()
        except Exception as e:
            details = 'diag_public_server_info() error occurred when attempting to connect to the Emby server. Error: ' + str(e)
            self.log.log(20, details)
            server_info['Error'] = details
            return connection_success, server_info

        if response.status_code != 200:
            logging.log(20, 'Non 200 status code returned when fetching public server info: ' + str(response.status_code))
        else:
            connection_success = True
        try:
            server_info = json.loads(response.text)
        except Exception as e:
            details = 'diag_public_server_info() failed to parse server details, error: ' + str(e)
            logging.log(20, details)
            server_info['Error'] = details

        return connection_success, server_info
