import logging
import requests
from enum import Enum
# NEW CODE 
import json
import random
import urllib.parse
from random import shuffle
import re
from .music_info import Music_info
# END NEW CODE

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
ITEMS_PLAYLIST_URL = "/emby/Items?Recursive=true&IncludeItemTypes=Playlist"
GET_PLAYLIST_URL = "/emby/Playlists/"
RECURSIVE_CLAUSE = "Recursive=true"
# END NEW CODE
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
    Handle the publically exposed emby endpoints
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
        # NEW CODE
        # self.playing = True                # will we be playing music (or just searching)?
        # END NEW CODE
    def get_server_info_public(self):
        return requests.get(self.host + SERVER_INFO_PUBLIC_URL)


class EmbyClient(PublicEmbyClient):
    """
    Handle communication to the Emby server
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
        Return specific Emby headers including auth token if available
        """
        media_browser_header = "MediaBrowser Client="+self.client +\
                               ", Device="+self.device +\
                               ", DeviceId="+self.client_id +\
                               ", Version="+self.version
        if self.auth and self.auth.user_id:
            media_browser_header = media_browser_header + ", UserId=" + self.auth.user_id
        headers = {"X-Emby-Authorization": media_browser_header}
        if self.auth and self.auth.token:
            headers["X-Emby-Token"] = self.auth.token
        return headers

    def search(self, query, media_types=[]):
        """
        Search for music using the Emby Search service
        """
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
        instant_item_mix = '/Items/{0}/InstantMix?userId={1}'.format(item_id, self.auth.user_id)
        return self._get(instant_item_mix)

    def get_song_file(self, song_id):
        url = '{0}{1}/{2}/{3}?{4}{5}'\
          .format(self.host, SONG_FILE_URL, song_id, AUDIO_STREAM, API_KEY, self.auth.token)
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
        HTTP post method with host and headers provided
        """
        return requests.post(self.host + url, json=payload, headers=self.get_headers())

    def _get(self, url):
        """
        HTTP get method with host and headers provided
        """
        return requests.get(self.host + url, headers=self.get_headers())

    # NEW CODE
    # Music playing vocabulary:
    # play {music_name}
    # play (track|song|title|) {track} by (artist|band|) {artist}
    # play (album|record) {album} by (artist|band) {artist}
    # play (any|all|my|random|some|) music 
    # play (playlist) {playlist}
    # play (genre) {genre}     
    #
    def _delete(self, url):  
      """
      HTTP delete method with host and headers provided
      """
      return requests.delete(self.host + url, headers=self.get_headers())

    def parse_music(self, phrase):
      """
      Perform "brute force" parsing of a music play request
      Returns 4 items:
      1. match_type: 
      """
      artist_name = "unknown-artist"
      found_by = "yes"                     # assume "by" is in the phrase
      intent = "unknown"                   # album, album-artist, artist, genre, music, playlist,
                                           #   track, track-artist, unknown-artist or unknown
      match_type = "unknown"               # album, artist, song or unknown
      music_name = ""                      # search term of music being sought
      track_uris = []                      # URIs of songs to be played

      phrase = phrase.lower()
      self.log.log(20, "parse_music() phrase in lower case: " + phrase)

      # check for a partial request with no music_name
      match phrase:
        case "album" | "track" | "song" | "artist" | "genre" | "playlist":
          self.log.log(20, "parse_music() not enough information in request "+str(phrase))
          mesg_info = {"phrase": phrase}
          self.log.log(20, "parse_music() mesg_info = "+str(mesg_info))
          ret_val = Music_info("song", "not_enough_info", {"phrase": phrase}, None)
          self.log.log(20, "parse_music() ret_val.mesg_info = "+str(ret_val.mesg_info))
          return ret_val
      key = re.split(" by ", phrase)
      if len(key) == 1:                    # did not find "by"
        found_by = "no"
        music_name = str(key[0])           # check for all music, genre and playlist
        self.log.log(20, "parse_music() music_name = "+music_name)
        match music_name:
          case "any music" | "all music" | "my music" | "random music" | "some music" | "music":
            self.log.log(20, "parse_music() removed keyword "+music_name+" from music_name")
            track_uris = self.get_music("music", music_name, artist_name)
            ret_val = Music_info("song", "playing_random", {}, track_uris)
            return ret_val
        key = re.split("^genre ", music_name)
        if len(key) == 2:                  # found first word "genre"
          genre = str(key[1])
          self.log.log(20, "parse_music() removed keyword "+music_name+" from music_name")
          ret_val = self.get_music("genre", genre, artist_name)
          return ret_val 
        else:
          key = re.split("^playlist ", music_name)
          if len(key) == 2:                # found first word "playlist"
            playlist = str(key[1])
            self.log.log(20, "parse_music() removed keyword "+music_name+" from music_name")
            ret_val = self.get_music("playlist", playlist, artist_name)
            return ret_val
      elif len(key) == 2:                  # found one "by"
        music_name = str(key[0])
        artist_name = str(key[1])          # artist name follows "by"
        self.log.log(20, "parse_music() found the word by - music_name = "+music_name+" artist_name = "+artist_name)
      elif len(key) == 3:                  # found "by" twice - assume first one is in music
        music_name = str(key[0]) + " by " + str(key[1]) # paste the track or album back together
        self.log.log(20, "parse_music() found the word by twice: assuming first is music_name")
        artist_name = str(key[2])
      else:                                # found more than 2 "by"s - what to do?
        music_name = str(key[0])

        # look for leading keywords in music_name
      key = re.split("^album |^record ", music_name)
      if len(key) == 2:                    # found first word "album" or "record"
        match_type = "album"
        music_name = str(key[1])
        if found_by == "yes":
          intent = "album-artist"
        else:
          intent = "album"
        self.log.log(20, "parse_music() removed keyword album or record")
      else:                                # leading "album" not found
        key = re.split("^track |^song |^title ", music_name)
        if len(key) == 2:                  # leading "track", "song" or "title" found
          music_name = str(key[1])
          match_type = "song"
          if found_by == "yes":            # assume artist follows 'by'
            intent = "track-artist"
          else:                            # assume track
            intent = "track"
          self.log.log(20, "parse_music() removed keyword track, song or title")
        else:                              # leading keyword not found
          key = re.split("^artist |^band ", music_name) # remove "artist" or "band" if first word
          if len(key) == 2:                # leading "artist" or "band" found
            music_name = "all_music"       # play all the songs they have
            artist_name = str(key[1])
            match_type = "artist"
            intent = "artist"
            self.log.log(20, "parse_music() removed keyword artist or band from music_name")
          else:                            # no leading keywords found yet
            self.log.log(20, "parse_music() no keywords found: in last else clause")
            if found_by == "yes":
              intent = "unknown-artist"    # found artist but music could be track or album
      key = re.split("^artist |^band ", artist_name) # remove "artist" or "band" if first word
      if len(key) == 2:                    # leading "artist" or "band" found in artist name
        artist_name = str(key[1])
        self.log.log(20, "parse_music() removed keyword artist or band from artist_name")
      self.log.log(20, "parse_music() calling get_music with: "+intent+", "+music_name+", "+artist_name)
      ret_val = self.get_music(intent, music_name, artist_name)
      return ret_val

    def get_track_ids(self, music_json):
      """
      given music JSON, return track IDs
      """
      track_ids = []
      num_recs = music_json["TotalRecordCount"]
      self.log.log(20, "get_track_ids() num_recs = "+str(num_recs))
      for i in range(num_recs):
        next_id = music_json["Items"][i]["Id"]
        track_ids.append(next_id)
      return track_ids
     
    def get_track_uris(self, music_json, do_shuffle=False):
      """
      given music JSON, return a maximum of MAX_TRACKS track URIs, and optionally shuffle them
      """
      track_ids = self.get_track_ids(music_json)
      track_uris = []
      if do_shuffle:                       # shuffle all tracks
        self.log.log(20, "get_track_uris() shuffling tracks")
        shuffle(track_ids)
      track_ids = track_ids[0:MAX_TRACKS]  # don't return too many
      self.log.log(20, "get_track_uris() track_ids = "+str(track_ids))
      for next_id in track_ids:
        track_uris.append(self.get_song_file(next_id))
      self.log.log(20, "get_track_uris() track_uris: "+str(track_uris))
      return track_uris

    def get_album(self, album_name, album_id, artist_name):
      """
      return URIs for one album by id if it is already found, or by name if not (album_id = -1)
      """
      track_uris = []
      mesg_file = ""
      mesg_info = {}
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
          ret_val = Music_info(None, None, None, None)
          return ret_val
        for i in range(num_hits):          # iterate through albums found - could be one
          album_found = albums_json["Items"][i]["Name"].lower()
          self.log.log(20, "get_album() comparing album_name "+str(album_name)+" with album_found "+album_found)
          if album_name == album_found:    # found the album
            album_id = albums_json["Items"][i]["Id"]
            artist_found = albums_json["Items"][i]["Artists"][0].lower()
            self.log.log(20, "get_album() found album "+album_name+" by artist "+str(artist_found)+" with ID "+str(album_id))
            break
        if album_id == -1:                 # album has still not been found
          self.log.log(20, "get_album() album "+str(album_name)+" was not found")
          ret_val = Music_info("album", None, None, None)
          return ret_val
      tracks = self.get_songs_by_album(album_id)  # get tracks on album, and convert to URIs
      self.log.log(20, "get_album() tracks = "+str(tracks))
      tracks_json = tracks.json()          # convert to JSON
      track_uris = self.get_track_uris(tracks_json)
      if artist_name != "unknown-artist":
        artist_found = tracks_json["Items"][0]["Artists"][0].lower()
        if artist_name != artist_found: # wrong artist - speak which artist is being played 
          self.log.log(20, "get_album() ====================>: playing album "+str(album_name)+" by "+str(artist_found)+" not by "+str(artist_name))
          mesg_file = "diff_album_artist"
          mesg_info = {"album_name": album_name, "artist_found": artist_found, "artist_name": artist_name}
      ret_val = Music_info("album", mesg_file, mesg_info, track_uris)
      return ret_val

    def get_artist(self, artist_name, artist_id):
      """
      return track URIs for artist either by ID if passed or by artist_name
      """
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
          ret_val = Music_info("Artist", None, None, None)
          return ret_val
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
      ret_val = Music_info("artist", "", {}, track_uris)
      return ret_val
 
    def get_all_music(self):
      """
      Return random tracks URIs from all music
      """
      track_uris = []                      # return value
      self.log.log(20, "get_all_music() play full random music")
      # searching with no search clause returns all tracks
      url = ITEMS_SEARCH_URL+'&'+RECURSIVE_CLAUSE+'&'+API_KEY+self.auth.token
      self.log.log(20, "get_all_music() all track IDs with Emby API: " + url)
      tracks = self._get(url)              # search for music
      tracks_json = tracks.json()
      num_recs = tracks_json["TotalRecordCount"]
      self.log.log(20, "get_all_music() number of records found = "+str(num_recs))
      if num_recs == 0:                    # music not found
        self.log.log(20, "Did not find music with emby API: "+str(url))
        ret_val = Music_info("song", None, None, None)
        return ret_val
      track_uris = self.get_track_uris(tracks_json, True) # shuffle tracks too
      ret_val = Music_info("song", "", {}, track_uris)
      return ret_val
      
    def get_genre(self, genre):
      """
      Given a genre name, return track URIs 
      """
      self.log.log(20, "TODO: finish code in get_genre() play genre: "+genre)
      ret_val = Music_info("song", None, None, None)
      return ret_val
      
    def get_playlist_id(self, playlist):
      """
      Given a playlist name, return its Id or -1 if not found
      """
      self.log.log(20, "get_playlist_id() called with playlist: "+str(playlist))
      encoded_playlist = urllib.parse.quote(playlist) # encode playlist name for URL
      url = ITEMS_PLAYLIST_URL+'&searchterm='+encoded_playlist+'&'+API_KEY+self.auth.token
      self.log.log(20, "get_playlist_id() getting playlist ID with url: " + url)
      playlists = self._get(url)           # search for playlist
      playlists_json = playlists.json()
      num_recs = playlists_json["TotalRecordCount"]
      self.log.log(20, "get_playlist_id() number of records found = "+str(num_recs))
      if num_recs == 0:                    # music not found
        self.log.log(20, "get_playlist_id() Did not find playlist "+playlist) 
        return -1 
      elif num_recs > 1:                   # more than one found
        self.log.log(20, "get_playlist_id() Ignoring multiple playlists") 
      playlist_id = playlists_json["Items"][0]["Id"]
      self.log.log(20, "get_playlist_id() playlist_id = "+str(playlist_id))
      return playlist_id

    def get_playlist(self, playlist):
      """
      Search for playlist and if found, return all tracks
      """
      track_uris = []    
      self.log.log(20, "get_playlist() called with playlist: "+playlist)
      playlist_id = self.get_playlist_id(playlist)
      if playlist_id == -1:                # playlist not found
        return Music_info("song", "playlist_not_found", {"playlist": playlist}, None)
      url = GET_PLAYLIST_URL+'/'+str(playlist_id)+'/Items?'+API_KEY+self.auth.token
      tracks = self._get(url)  
      tracks_json = tracks.json()
      num_recs = tracks_json["TotalRecordCount"]
      track_uris = self.get_track_uris(tracks_json, True) # shuffle tracks too
      self.log.log(20, "get_playlist() type of track_uris = "+str(type(track_uris)))
      return Music_info("song", "", {}, track_uris)
      
    def get_track(self, track_name, artist_name):
      """
      Get track by id if passed, but if -1, get track by name
      """
      track_uris = []
      mesg_file = ""
      mesg_info = {}
      self.log.log(20, "get_track() called with track_name "+track_name+" artist_name "+artist_name)
      encoded_track_name = urllib.parse.quote(track_name) # encode track name for URL
      url = '{0}{1}&{2}&{3}{4}'.format(ITEMS_SEARCH_URL, encoded_track_name, RECURSIVE_CLAUSE, API_KEY, self.auth.token)
      self.log.log(20, "get_track() getting track ID with Emby API: " + url)
      tracks = self._get(url)              # search for music
      tracks_json = tracks.json()
      num_recs = tracks_json["TotalRecordCount"]
      self.log.log(20, "get_track() number of records found = "+str(num_recs))
      if num_recs == 0:                    # music not found
        self.log.log(20, "Did not find music with emby API: "+str(url))
        return None
      if num_recs > 1:                     # multiple tracks with same name found
        index = random.randrange(num_recs) # pick random track/record/artist if multiple returned
      else:                                # only one track
        index = 0
      artist_found = tracks_json["Items"][index]["AlbumArtist"].lower()
      album_found = tracks_json["Items"][index]["Album"].lower()
      type_found = tracks_json["Items"][index]["Type"]
      self.log.log(20, "get_track() type_found = "+str(type_found))
      if num_recs > 1:                     # speak which track was chosen
        self.log.log(20, "get_track(): ====================>: playing track "+str(track_name)+" by artist "+artist_found+" from album "+album_found)
        mesg_file = "playing_track"
        mesg_info = {"track_name": track_name, "artist_name": artist_found, "album_name": album_found}
      track_id = tracks_json["Items"][index]["Id"]
      track_uris.append(self.get_song_file(track_id))
      self.log.log(20, "get_track() track_uris = "+str(track_uris))

      # if artist was specified, verify it is correct
      if artist_name != "unknown-artist" and artist_name != artist_found: # wrong artist - speak correct artist before playing 
        self.log.log(20, "get_track() ====================>: playing album "+str(album_found)+" by "+str(artist_found)+" not by "+str(artist_name))
        mesg_file = "diff_artist"
        mesg_info = {"track_name": track_name, "album_name": album_found, "artist_found": artist_found, "artist_name": artist_name}
      ret_val = Music_info("song", mesg_file, mesg_info, track_uris)
      return ret_val 

    def get_unknown_music(self, music_name, artist_name):
      """
      Search on a music search term  - could be album, artist or track
      """
      match_type = ""
      track_uris = []
      mesg_file = ""
      mesg_info = {}
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
        ret_val = Music_info("song", None, None, None)
        return ret_val
      type_found = tracks_json["Items"][0]["Type"]
      self.log.log(20, "get_unknown_music() type_found = "+str(type_found))
      match type_found:
        case "Audio":                    
          ret_val = self.get_track(music_name, artist_name)
        case "MusicAlbum": 
          # we have an album ID - if artist was specified, be sure it is correct
          if artist_name != "unknown-artist":  # artist was requested
            self.log.log(20, "get_unknown_music() checking for correct artist")
            artist_found = tracks_json["Items"][0]["AlbumArtist"].lower() 
          album_name = tracks_json["Items"][0]["Name"].lower()
          album_id = tracks_json["Items"][0]["Id"]
          artist_found = tracks_json["Items"][0]["Name"][0].lower()
          self.log.log(20, "get_unknown_music() type is MusicAlbum: calling get_album()")
          ret_val = self.get_album(album_name, album_id, artist_name) 
        case "MusicArtist": 
          artist_found = tracks_json["Items"][0]["Name"][0].lower()
          artist_name = tracks_json["Items"][0]["Name"].lower()
          artist_id = tracks_json["Items"][0]["Id"]
          self.log.log(20, "get_unknown_music() type is MusicArtist: calling get_artist()")
          ret_val = self.get_artist(artist_name, artist_id) 
        case _:  
          self.log.log(20, "get_unknown_music() WARNING unexpected type_found: "+type_found)
          track_uris = None
      return ret_val
      
    def get_music(self, intent, music_name, artist_name):
      """
      Search for track_uris with one search terms and an optional artist name
      intent can be: album, album-artist, artist, music, track, track-artist, unknown-artist or unknown
      call one of:
        get_album()         play an album
        get_artist()        play an artist
        get_all_music()     play "full random" 
        get_genre()         play a music genre 
        get_playlist()      play a saved playlist
        get_track()         play a specific track
        get_unknown_music() play something that might be a album, artist or track 
      """
      self.log.log(20, "get_music() intent = "+intent+" music_name = "+music_name+" artist_name = "+artist_name) 
      match intent:
        case "album":
          ret_val = self.get_album(music_name, -1, "unknown-artist") # no album id
        case "album-artist":
          ret_val = self.get_album(music_name, -1, artist_name) # no album id
        case "artist":
          ret_val = self.get_artist(artist_name, -1) # no artist_id 
        case "genre":                   
          ret_val = self.get_genre(music_name) 
        case "music":                      # full random
          ret_val = self.get_all_music()
        case "playlist": 
          ret_val = self.get_playlist(music_name)  
        case "track":                      # call get_track with unknown track ID
          ret_val = self.get_track(music_name, "unknown-artist")
        case "track-artist":           
          ret_val = self.get_track(music_name, artist_name)
        case "unknown-artist":
          ret_val = self.get_unknown_music(music_name, artist_name)
        case "unknown":
          ret_val = self.get_unknown_music(music_name, "unknown-artist")
        case _:                            # unexpected
          self.log.log(20, "get_music() INTERNAL ERROR: intent is not supposed to be: "+str(intent))
          ret_val = Music_info(None, None, None, None) 
    #  track_uris = ret_val.track_uris  
    #  ret_val = Music_info(match_type, mesg_file, mesg_info, track_uris)
      self.log.log(20, "get_music() - ret_val.track_uris of type "+str(type(ret_val.track_uris))) 
      return ret_val
    
    def get_id_from_uri(self, track_uris):
      """
      Given a track URI, return the track Id
      """
      self.log.log(20, "get_id_from_uri() track_uris = "+str(track_uris))
      key = re.split("/Audio/", str(track_uris)) # track ID is to the right
      if len(key) == 1:                    # unexpected 
        self.log.log(20, "get_id_from_uri() UNEXPECTED: '/Audio/' not found in track_uris")
        return None
      uri_suffix = key[1]
      key = re.split("/", uri_suffix)
      return key[0]

    def create_playlist(self, phrase):
      """
      Create requires a playlist name and music name as Emby playlists cannot be empty
      Vocabulary:  (create|make) playlist {playlist} from (track|song|title) {track}
      """
    # self.playing = False                 # will not be playing music
      phrase = " ".join(phrase)            # convert list back to string
      phrase_encoded = urllib.parse.quote(phrase) # encode playlist name
      self.log.log(20, "create_playlist() called with phrase: "+phrase)
      key = re.split("from track |from song |from title ", phrase)
      if len(key) == 1:                    # unexpected 
        self.log.log(20, "create_playlist() 'from track' not found in phrase")
        mesg_info = {"phrase": phrase} 
        return 'missing_from', mesg_info
      playlist_name = key[0]
      music_name = key[1]
      self.log.log(20, "create_playlist() playlist_name = "+playlist_name+" music_name = "+music_name)

      # check if playlist already exists
      playlist_id = self.get_playlist_id(playlist_name) # search for playlist first
      if playlist_id != -1:                # it exists
        self.log.log(20, "create_playlist() playlist already exists: "+playlist_name)
        mesg_info = {"playlist_name": playlist_name} 
        return "playlist_exists", mesg_info

      # parse_music() returns URIs from which the track ID can be obtained (yes, a bit kludgy)
      # sample URI: ['http://192.168.1.229:8096/Audio/3329/stream.mp3?api_key=API_KEY']
      music_info = self.parse_music(music_name) 
      if music_info.track_uris == None:       # did not find track/album
        self.log.log(20, "create_playlist() did not find track "+music_name)
        mesg_file = "cannot_create_playlist"
        mesg_info = {"playlist_name": playlist_name, "music_name": music_name} 
        return mesg_file, mesg_info
      self.log.log(20, "create_playlist() music_info.track_uris = "+str(music_info.track_uris))
      track_id = self.get_id_from_uri(music_info.track_uris)
      self.log.log(20, "create_playlist() track_id = "+track_id)
      payload = {'Name': playlist_name, 'Ids': track_id, 'MediaType': 'Playlists'}
      payload.update(self.get_headers())
      url = GET_PLAYLIST_URL+"?"+API_KEY+self.auth.token
      self.log.log(20, "create_playlist() url = "+url)
      self.log.log(20, "create_playlist() payload = "+str(payload))
      response = self._post(url, payload)
      self.log.log(20, "create_playlist() response.status_code = "+str(response.status_code))
      if 200 <= response.status_code < 300:
        mesg_info = {'playlist_name': playlist_name}
        return "created_playlist", mesg_info
      else:
        mesg_info = {'status_code': status_code}
        return "bad_emby_api", mesg_info

    def delete_playlist(self, playlist_name):
      """
      Delete a playlist
      Vocabulary: (delete|remove) playlist {playlist}
      """
      self.log.log(20, "delete_playlist() called with phrase: "+str(playlist_name))
      return False

    def get_playlist_track_ids(self, playlist_id):
      """
      Given a playlist ID, return all associated track IDs  
      """
      url = ITEMS_URL+"?"+ITEMS_PARENT_ID_KEY+"="+playlist_id+"&recursive=true&"+API_KEY+self.auth.token
      self.log.log(20, "get_playlist_track_ids() url = "+str(url)) 
      track_uris = self._get(url)
      tracks_json = track_uris.json()
      track_ids = self.get_track_ids(tracks_json) 
      self.log.log(20, "get_playlist_track_ids() track_ids = "+str(track_ids))
      return track_ids  
      
    def add_to_playlist(self, phrase):
      """
      Add a track or album to an existing playlist
      Vocabulary:
        add (track|song|title) {track} to playlist {playlist}
        add (album|record) {album} to playlist {playlist}
      """
      phrase = " ".join(phrase)            # convert list back to string
      self.log.log(20, "add_to_playlist() called with phrase: "+phrase)
      key = re.split(" to playlist| two playlist| 2 playlist ", phrase)
      if len(key) == 1:                    # did not find "to playlist"
        self.log.log(20, "add_to_playlist() ERROR 'to playlist' not found in phrase")
        return "to_playlist_missing", {} 
      music_name = key[0]
      playlist_name = key[1] 
      self.log.log(20, "add_to_playlist() music_name = "+music_name+" playlist_name = "+playlist_name)

      # verify playlist exists
      playlist_id = self.get_playlist_id(playlist_name) 
      if playlist_id == -1:                # not found
        self.log.log(20, "add_to_playlist() did not find playlist_name "+playlist_name)
        mesg_info = {'playlist_name': playlist_name}
        return "missing_playlist", mesg_info
      
      # verify track or album exists - parse_music() returns URIs but we want track IDs 
      music_info = self.parse_music(music_name) 
      if music_info.track_uris == None:
        self.log.log(20, "add_to_playlist() did not find track or album "+music_name)
        mesg_info = {"playlist_name": playlist_name, "music_name": music_name} 
        return "playlist_missing_track", mesg_info
      self.log.log(20, "add_to_playlist() music_info.track_uris = "+str(music_info.track_uris))
      track_id = self.get_id_from_uri(music_info.track_uris)
      self.log.log(20, "add_to_playlist() track_id = "+track_id)

      # verify track is not already in playlist
      track_ids = self.get_playlist_track_ids(playlist_id)
      self.log.log(20, "add_to_playlist() track_ids in playlist = "+str(track_ids))
      if track_id in track_ids:            # track is already in playlist
        self.log.log(20, "add_to_playlist() track_id = "+track_id)
        mesg_info = {'music_name': music_name, 'playlist_name': playlist_name}
        return "track_in_playlist", mesg_info

      # add track to playlist  
      payload = {'Ids': track_id, 'UserId': self.auth.user_id}
      payload.update(self.get_headers())
      url = GET_PLAYLIST_URL+playlist_id+'/Items?'+API_KEY+self.auth.token
      self.log.log(20, "add_to_playlist() url = "+url)
      self.log.log(20, "add_to_playlist() payload = "+str(payload))
      response = self._post(url, payload)
      self.log.log(20, "add_to_playlist() response.status_code = "+str(response.status_code))
      if 200 <= response.status_code < 300:
        mesg_info = {'music_name': music_name, 'playlist_name': playlist_name}
        return "ok_its_done", mesg_info
      else:
        mesg_info = {'status_code': response.status_code}
        return "bad_emby_api", mesg_info
      
   
    def delete_from_playlist(self, phrase):
      """
      Delete a track from a playlist
      Vocabulary:
        (remove|delete) (track|song|title) {track} from playlist {playlist}
        (remove|delete) (album|record) {album} from playlist {playlist}
      """
      self.log.log(20, "delete_from_playlist() called with phrase: "+str(phrase))
      return False  
    # END NEW CODE
    
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
