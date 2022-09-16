import logging
import requests
from enum import Enum
# NEW CODE
import json
import random
import urllib.parse
from random import shuffle
# end NEW CODE

# url constants
AUTHENTICATE_BY_NAME_URL = "/Users/AuthenticateByName"
SEARCH_HINTS_URL = "/Search/Hints"
ARTISTS_URL = "/Artists"
ARTIST_INSTANT_MIX_URL = ARTISTS_URL + "/InstantMix"
SONG_FILE_URL = "/Audio"
DOWNLOAD_URL = "/Download"
ITEMS_ARTIST_KEY = "ArtistIds"
ITEMS_PARENT_ID_KEY = "ParentId"
ITEMS_URL = "/Items"
# NEW CODE
ITEMS_ARTIST_ID_URL = "/emby/Artists?searchterm="
ITEMS_SEARCH_URL = "/emby/Items?searchterm="
MAX_TRACKS = 50                            # maximum songs to queue up
RECURSIVE_CLAUSE = "Recursive=true"
# end NEW CODE
ITEMS_ALBUMS_URL = ITEMS_URL + "/?SortBy=SortName&SortOrder=Ascending&IncludeItemTypes=MusicAlbum&Recursive=true&" + ITEMS_ARTIST_KEY + "="
ITEMS_SONGS_BY_ARTIST_URL = ITEMS_URL + "/?SortBy=SortName&SortOrder=Ascending&IncludeItemTypes=Audio&Recursive=true&" + ITEMS_ARTIST_KEY + "="
ITEMS_SONGS_BY_ALBUM_URL = ITEMS_URL + "/?SortBy=IndexNumber&" + ITEMS_PARENT_ID_KEY + "="
LIMIT = "&Limit="
SERVER_INFO_URL = "/System/Info"
SERVER_INFO_PUBLIC_URL = SERVER_INFO_URL + "/Public"
# auth constants
AUTH_USERNAME_KEY = "Username"
AUTH_PASSWORD_KEY = "Pw"

# query param constants
AUDIO_STREAM = "stream.mp3"
API_KEY = "api_key="


class PublicEmbyClient(object):
    """
    Handles the publically exposed emby endpoints

    """

    def __init__(self, host, device="noDevice", client="NoClient", client_id="1234", version="0.1"):
        """
        Sets up the connection to the Emby server
        :param host:
        """
        self.log = logging.getLogger(__name__)
        self.host = host
        self.auth = None
        self.device = device
        self.client = client
        self.client_id = client_id
        self.version = version

    def get_server_info_public(self):
        return requests.get(self.host + SERVER_INFO_PUBLIC_URL)


class EmbyClient(PublicEmbyClient):
    """
    Handles communication to the Emby server

    """

    def __init__(self, host, username, password, device="noDevice", client="NoClient", client_id="1234", version="0.1"):
        """
        Sets up the connection to the Emby server
        :param host:
        :param username:
        :param password:
        """

        super().__init__(host, device, client, client_id, version)
        self.log = logging.getLogger(__name__)
        self.auth = self._auth_by_user(username, password)

    def _auth_by_user(self, username, password):
        """
        Authenticates to emby via username and password

        :param username:
        :param password:
        :return:
        """
        auth_payload = \
            {AUTH_USERNAME_KEY: username, AUTH_PASSWORD_KEY: password}
        response = self._post(AUTHENTICATE_BY_NAME_URL, auth_payload)
        assert response.status_code == 200
        return EmbyAuthorization.from_response(response)

    def get_headers(self):
        """
        Returns specific Emby headers including auth token if available

        :return:
        """
        media_browser_header = "MediaBrowser Client="+self.client +\
                               ", Device="+self.device +\
                               ", DeviceId="+self.client_id +\
                               ", Version="+self.version
        if self.auth and self.auth.user_id:
            media_browser_header = \
                media_browser_header + ", UserId=" + self.auth.user_id
        headers = {"X-Emby-Authorization": media_browser_header}
        if self.auth and self.auth.token:
            headers["X-Emby-Token"] = self.auth.token

        return headers

    def search(self, query, media_types=[]):

        query_params = '?SearchTerm={0}'.format(query)

        types = None
        for type in media_types:
            types = type + ","

        if types:
            types = types[:len(types) - 1]
            query_params = query_params + '&IncludeItemTypes={0}'.format(types)

        self.log.log(20, "search() query_params = "+query_params)
        return self._get(SEARCH_HINTS_URL + query_params)

    def instant_mix(self, item_id):
        # userId query param is required even though its not required in swagger
        # https://emby.media/community/index.php?/topic/50760-instant-mix-api-value-cannot-be-null-error/
        instant_item_mix = '/Items/{0}/InstantMix?userId={1}'\
            .format(item_id, self.auth.user_id)
        return self._get(instant_item_mix)

    def get_song_file(self, song_id):
        url = '{0}{1}/{2}/{3}?{4}{5}'\
            .format(self.host, SONG_FILE_URL,
                    song_id, AUDIO_STREAM, API_KEY, self.auth.token)
        return url

    def get_albums_by_artist(self, artist_id):
        url = ITEMS_ALBUMS_URL + str(artist_id)
        return self._get(url)

    def get_songs_by_artist(self, artist_id, album):
        response = self.client.get_songs_by_artist(artist_id, album)
        return self.convert_response_to_playable_songs(response)

    def get_songs_by_album(self, album_id):
        #url = ITEMS_SONGS_BY_ALBUM_URL + str(album_id)
        url = ITEMS_SONGS_BY_ALBUM_URL+str(album_id)+"&Recursive=true&"+API_KEY+self.auth.token 
        self.log.log(20, "get_songs_by_album() url = "+str(url))
        ret_val = self._get(url)
        self.log.log(20, "get_songs_by_album() ret_val = "+str(ret_val))
        return ret_val

    def get_all_artists(self):
        return self._get(ARTISTS_URL)

    def get_server_info(self):
        return self._get(SERVER_INFO_URL)

    def _post(self, url, payload):
        """
        Post with host and headers provided

        :param url:
        :param payload:
        :return:
        """
        return requests.post(
            self.host + url, json=payload, headers=self.get_headers())

    def _get(self, url):
        """
        Get with host and headers provided

        :param url:
        :return:
        """
        return requests.get(self.host + url, headers=self.get_headers())

    # NEW CODE
    # get_music() calls one of:
    #  get_album()         play an album
    #  get_artist()        play an artist
    #  get_all_music()     play "fully random" 
    #  get_genre()         play a music genre 
    #  get_playlist()      play a saved playlist
    #  get_track()         play a specific track
    #  get_unknown_music() play something that might be a album, artist or track 
    # return URIs of all tracks to be played
    #
    # return a maximum of MAX_TRACKS track URIs from JSON, optionally shuffle them
    def get_track_uris(self, music_json, do_shuffle=False):
      track_ids = []
      track_uris = []
      num_recs = music_json["TotalRecordCount"]
      self.log.log(20, "get_track_uris() num_recs = "+str(num_recs))
      for i in range(num_recs):
        next_id = music_json["Items"][i]["Id"]
        track_ids.append(next_id)
      if do_shuffle:                       # shuffle all tracks
        shuffle(track_ids)
      track_ids = track_ids[0:MAX_TRACKS]  # dont return too many
      self.log.log(20, "get_track_uris() track_ids = "+str(track_ids))
      for next_id in track_ids:
        track_uris.append(self.get_song_file(next_id))
      self.log.log(20, "get_track_uris() track_uris: "+str(track_uris))
      return track_uris

    # get album by id if it is already found, or by name if not (album_id = -1)
    def get_album(self, album_name, album_id, artist_name):
      self.log.log(20, "get_album() album_name = "+album_name+" artist_name = "+artist_name)
      track_uris = []                      # return value
      artist_found = "none"
      if album_id == -1:                   # no album yet
        url = ITEMS_SEARCH_URL+str(album_name)+"&IncludeItemTypes=MusicAlbum&Recursive=true&"+API_KEY+self.auth.token
        self.log.log(20, "get_album(): calling self._get with url: "+str(url))
        albums = self._get(url)            # search for album
        albums_json = albums.json()
        num_hits = albums_json["TotalRecordCount"]
        self.log.log(20, "get_album() num_hits = " + str(num_hits))
        if num_hits == 0:                  # album not found
          self.log.log(20, "get_album() _get() did not find an album matching "+str(album_name))
          return None
        for i in range(num_hits):          # iterate through albums found - could be one
          album_found = albums_json["Items"][i]["Name"].lower()
          self.log.log(20, "get_album() comparing album_name "+str(album_name)+" with album_found "+album_found)
          if album_name == album_found:    # found the album
            album_id = albums_json["Items"][i]["Id"]
            artist_found = albums_json["Items"][i]["Artists"][0].lower()
            self.log.log(20, "get_album() found album "+album_name+" by artist "+str(artist_found)+" with ID "+str(album_id))
            break
        if album_id == -1:                   # album has still not been found
          self.log.log(20, "get_album() album "+str(album_name)+" was not found")
          return None
      if artist_name != "unknown-artist":       # artist was requested, is it correct?
        self.log.log(20, "get_album() checking for correct artist")
        if artist_name != artist_found:         # wrong artist but playing what was found is better than failing 
          self.log.log(20, "get_album() ====================>: playing album "+str(album_name)+" by "+str(artist_found)+" not by "+str(artist_name))
      
      # get the tracks on the album, and convert to URIs
      tracks = self.get_songs_by_album(album_id)
      self.log.log(20, "get_album() tracks = "+str(tracks))
      tracks_json = tracks.json()          # convert to JSON
      track_uris = self.get_track_uris(tracks_json)
      return track_uris

    # get artist either by ID if passed or by artist_name
    def get_artist(self, artist_name, artist_id):
      track_uris = []                      # return value
      self.log.log(20, "get_artist() called with artist_name "+str(artist_name))
      if artist_id == -1:                  # need to find it
        artist_encoded = urllib.parse.quote(artist_name) # encode artist name
        url = '{0}{1}&{2}{3}'.format(ITEMS_ARTIST_ID_URL, artist_encoded, API_KEY, self.auth.token)
        self.log.log(20, "get_artist() getting artist ID with emby API: "+str(url))
        artist = self._get(url)            # search for artist
        artist_json = artist.json()        # convert to JSON
        num_artists = artist_json["TotalRecordCount"]
        self.log.log(20, "get_artist() num_artists = "+str(num_artists))
        if num_artists == 0:               # artist not found
          self.log.log(20, "get_artist() did not find music for artist "+str(artist))
          return None
        artist_id = artist_json["Items"][0]["Id"]
        self.log.log(20, "get_artist() found artist ID "+artist_id+" with emby API: "+str(url))

      # have artist ID, get the tracks
      url = ITEMS_SONGS_BY_ARTIST_URL + str(artist_id) + "&" + API_KEY + self.auth.token
      self.log.log(20, "get_artist() getting songs by artist with url: "+str(url))
      tracks = self._get(url)
      self.log.log(20, "get_artist() found tracks: "+str(tracks))
      tracks_json = tracks.json()
      num_recs = tracks_json["TotalRecordCount"]
      self.log.log(20, "get_artist() number of records found = "+str(num_recs))
      track_uris = self.get_track_uris(tracks_json, True) # do shuffle tracks
      return track_uris

    # play random tracks from all music 
    def get_all_music(self):
      track_uris = []                      # return value
      self.log.log(20, "get_all_music() play full random music")
      # searching with no search clause returns all tracks
      url = ITEMS_SEARCH_URL+'&'+RECURSIVE_CLAUSE+'&'+API_KEY+'&'+self.auth.token
      self.log.log(20, "get_all_music() all track IDs with Emby API: " + url)
      tracks = self._get(url)              # search for music
      tracks_json = tracks.json()
      num_recs = tracks_json["TotalRecordCount"]
      self.log.log(20, "get_track() number of records found = "+str(num_recs))
      if num_recs == 0:                    # music not found
        self.log.log(20, "Did not find music with emby API: "+str(url))
        return None
      track_uris = self.get_track_uris(tracks_json, True) # shuffle tracks too
      return track_uris
      
    def get_genre(self, genre):
      self.log.log(20, "TODO: finish code in get_genre() play genre: "+genre)
      return None # for now
      
    def get_playlist(self, playlist):
      self.log.log(20, "TODO: finish code in get_playlist() play playlist: "+playlist)
      return None # for now
      
    # get track by id if passed, but if -1, get track by name
    def get_track(self, track_name, track_id, artist_name):
      self.log.log(20, "get_track() called with track_name "+track_name+" track_id "+str(track_id)+" artist_name "+artist_name)
      track_uris = []
      if track_id == -1:                   # have not searched for track yet
        encoded_track_name = urllib.parse.quote(track_name) # encode track name for URL
        url = '{0}{1}&{2}&{3}{4}'.format(ITEMS_SEARCH_URL, encoded_track_name, RECURSIVE_CLAUSE, API_KEY, self.auth.token)
        self.log.log(20, "get_track() getting track ID with Emby API: " + url)
        tracks = self._get(url)            # search for music
        tracks_json = tracks.json()
        num_recs = tracks_json["TotalRecordCount"]
        self.log.log(20, "get_track() number of records found = "+str(num_recs))
        if num_recs == 0:                  # music not found
          self.log.log(20, "Did not find music with emby API: "+str(url))
          return None
        if num_recs > 1:                   # multiple tracks with same name found
          index = random.randrange(num_recs) # random track/record/artist if multiple returned
          artist_found = tracks_json["Items"][index]["AlbumArtist"]
          album_found = tracks_json["Items"][index]["Album"]
          self.log.log(20, "get_track(): ====================>: playing track "+str(track_name)+" by artist "+artist_found+" from album "+album_found)
        else:                              # only one track
          index = 0
        type_found = tracks_json["Items"][index]["Type"]
        self.log.log(20, "get_track() type_found = "+str(type_found))
        track_id = tracks_json["Items"][index]["Id"]
      # url = '{0}{1}/{2}/{3}?{4}{5}'.format(self.host, SONG_FILE_URL, track_id, AUDIO_STREAM, API_KEY, self.auth.token)
      track_uris.append(self.get_song_file(track_id))
      self.log.log(20, "get_track() track_uris = "+str(track_uris))
      return track_uris 

    # search on a music search term  - could be album, artist or track
    def get_unknown_music(self, music_name, artist_name):
      self.log.log(20, "get_unknown_music() music_name = "+music_name+" artist_name = "+artist_name)
      encoded_music_name = urllib.parse.quote(music_name) # encode track name for URL
      url = '{0}{1}&{2}&{3}{4}'.format(ITEMS_SEARCH_URL, encoded_music_name, RECURSIVE_CLAUSE, API_KEY, self.auth.token)
      self.log.log(20, "get_unknown_music() getting track ID with emby API: " + url)
      tracks = self._get(url)              # search for music
      tracks_json = tracks.json()  
      num_recs = tracks_json["TotalRecordCount"]
      self.log.log(20, "get_unknown_music() number of records found = "+str(num_recs))
      if num_recs == 0:                    # music not found
        self.log.log(20, "get_unknown_music() did not find music with emby API: "+str(url))
        return None
      type_found = tracks_json["Items"][0]["Type"]
      self.log.log(20, "get_unknown_music() type_found = "+str(type_found))
      match type_found:
        case "Audio":                    
          if num_recs > 1:                     # multiple tracks with same name found
            index = random.randrange(num_recs) # select random track
            artist_found = tracks_json["Items"][index]["AlbumArtist"]
            self.log.log(20, "get_unknown_music() ====================>: playing track "+str(music_name)+" by artist "+artist_found)
          else:                                # only one hit
            index = 0
          track_name = tracks_json["Items"][index]["Name"].lower()
          track_id = tracks_json["Items"][index]["Id"]
          self.log.log(20, "get_unknown_music() type is Audio: calling get_track()")
          track_uris = self.get_track(track_name, track_id, "unknown-artist") 
        case "MusicAlbum": 
          # we have an album ID - if artist was specified, be sure it is correct
          if artist_name != "unknown-artist":  # artist was requested
            self.log.log(20, "get_unknown_music() checking for correct artist")
            artist_found = tracks_json["Items"][0]["AlbumArtist"].lower()
            if artist_name != artist_found:    # wrong artist
              self.log.log(20, "get_unknown_music() ====================>: playing album "+str(music_name)+" by "+str(artist_found)+" not by "+str(artist_name))
              # Playing what was found is better than failing 
          album_name = tracks_json["Items"][0]["Name"].lower()
          album_id = tracks_json["Items"][0]["Id"]
          self.log.log(20, "get_unknown_music() type is MusicAlbum: calling get_album()")
          track_uris = self.get_album(album_name, album_id, "unknown-artist") 
        case "MusicArtist": 
          artist_found = tracks_json["Items"][0]["Name"][0].lower()
          artist_name = tracks_json["Items"][0]["Name"].lower()
          artist_id = tracks_json["Items"][0]["Id"]
          self.log.log(20, "get_unknown_music() type is MusicArtist: calling get_artist()")
          track_uris = self.get_artist(artist_name, artist_id) 
        case _:  
          self.log.log(20, "get_unknown_music() WARNING unexpected type_found: "+type_found)
          track_uris = None
      return track_uris
      
    # search for track_uris with one search terms and an optional artist name
    # intent can be: album, album-artist, artist, music, track, track-artist, unknown-artist or unknown
    def get_music(self, intent, music_name, artist_name):
      self.log.log(20, "get_music() intent = "+intent+" music_name = "+music_name+" artist_name = "+artist_name) 
      track_uris = []
      match intent:
        case "album":
          track_uris = self.get_album(music_name, -1, "unknown-artist") # no album id
        case "album-artist":
          track_uris = self.get_album(music_name, -1, artist_name) # no album id
        case "artist":
          track_uris = self.get_artist(artist_name, -1) # no artist_id 
        case "genre":                   
          track_uris = self.get_genre(music_name)    # TODO: write this code!
        case "music":                      # full random
          track_uris = self.get_all_music()
        case "playlist": 
          track_uris = self.get_playlist(music_name) # TODO: write this code!
        case "track":                      # call get_track with unknown track ID
          track_uris = self.get_track(music_name, -1, "unknown-artist")
        case "track-artist":           
          track_uris = self.get_track(music_name, -1, artist_name)
        case "unknown-artist":
          track_uris = self.get_unknown_music(music_name, artist_name)
        case "unknown":
          track_uris = self.get_unknown_music(music_name, "unknown-artist")
        case _:                            # unexpected
          self.log.log(20, "get_music() INTERNAL ERROR: intent is not supposed to be: "+str(intent))
          return None 
      self.log.log(20, "get_music() track_uris = "+str(track_uris))
      return track_uris 
    # end NEW CODE
    
class EmbyAuthorization(object):

    def __init__(self, user_id, token):
        self.user_id = user_id
        self.token = token

    @classmethod
    def from_response(cls, response):
        """
        Helper method for converting a response into
        an Emby Authorization

        :param response:
        :return:
        """
        auth_content = response.json()
        return EmbyAuthorization(
            auth_content["User"]["Id"], auth_content["AccessToken"])


class EmbyMediaItem(object):

    """
    Stripped down representation of a media item in Emby

    """

    def __init__(self, id, name, type):
        self.id = id
        self.name = name
        self.type = type

    @classmethod
    def from_item(cls, item):
        media_item_type = MediaItemType.from_string(item["Type"])
        return EmbyMediaItem(item["Id"], item["Name"], media_item_type)

    @staticmethod
    def from_list(items):
        media_items = []
        for item in items:
            media_items.append(EmbyMediaItem.from_item(item))

        return media_items


class MediaItemType(Enum):
    ARTIST = "MusicArtist"
    ALBUM = "MusicAlbum"
    SONG = "Audio"
    OTHER = "Other"

    @staticmethod
    def from_string(enum_string):
        for item_type in MediaItemType:
            if item_type.value == enum_string:
                return item_type
        return MediaItemType.OTHER
