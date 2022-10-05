import hashlib
from mycroft import intent_file_handler
from mycroft.skills.common_play_skill import CommonPlaySkill, CPSMatchLevel
from mycroft.skills.audioservice import AudioService
from mycroft.api import DeviceApi

from .emby_croft import EmbyCroft
from .music_info import Music_info

class Emby(CommonPlaySkill):

    def __init__(self):
        super().__init__()
        self._setup = False
        self.audio_service = None
        self.emby_croft = None
        self.device_id = hashlib.md5(
            ('Emby'+DeviceApi().identity.uuid).encode())\
            .hexdigest()

    def initialize(self):
        pass

    @intent_file_handler('emby.intent')
    def handle_emby(self, message):

        self.log.log(20, message.data)

        # first thing is connect to emby or bail
        if not self.connect_to_emby():
            self.speak_dialog('configuration_fail')
            return

        # determine intent
        intent, intent_type = EmbyCroft.determine_intent(message.data)

        songs = []
        try:
            songs = self.emby_croft.handle_intent(intent, intent_type)
        except Exception as e:
            self.log.log(20, "handle_emby() e = "+e)
            self.speak_dialog('play_fail', {"media": intent})

        if not songs or len(songs) < 1:
            self.log.log(20, 'handle_emby(): no songs Returned')
            self.speak_dialog('play_fail', {"media": intent})
        else:
            # setup audio service and play
            self.audio_service = AudioService(self.bus)
            self.speak_playing(intent)
            self.audio_service.play(songs, message.data['utterance'])

    def speak_playing(self, media):
        data = dict()
        data['media'] = media
        self.speak_dialog('emby', data)

    @intent_file_handler('diagnostic.intent')
    def handle_diagnostic(self, message):

        self.log.log(20, "handle_diagnostic(): message.data = " + message.data)
        self.speak_dialog('diag_start', wait=True)

        # connect to emby for diagnostics
        self.connect_to_emby(diagnostic=True)
        connection_success, info = self.emby_croft.diag_public_server_info()

        if connection_success:
            self.speak_dialog('diag_public_info_success', info,  wait=True)
        else:
            self.speak_dialog('diag_public_info_fail', {'host': self.settings['hostname']},  wait=True)
            self.speak_dialog('general_check_settings_logs',  wait=True)
            self.speak_dialog('diag_stop')
            return

        if not self.connect_to_emby():
            self.speak_dialog('diag_auth_fail',  wait=True)
            self.speak_dialog('diag_stop')
            return
        else:
            self.speak_dialog('diag_auth_success',  wait=True)

        self.speak_dialog('diagnostic')

    # NEW CODE - for manipulating playlists
    @intent_file_handler('playlist.intent')
    def handle_playlist(self, message):
      utterance = str(message.data["utterance"])
      self.log.log(20, "handle_playlist(): utterance = "+utterance) 
      if not self.connect_to_emby():        # connect to emby or bail
        self.speak_dialog('configuration_fail')
        return

      # return value is file name of .dialog file to speak and values to be plugged in
      mesg_info = []
      mesg_file, mesg_info = self.emby_croft.manipulate_playlists(utterance)
      if [ mesg_file != None ]:                # there is a reply to speak
        self.speak_dialog(mesg_file, data=mesg_info, wait=True)
    # END NEW CODE

    def stop(self):
        pass

    def CPS_start(self, phrase, data):
        """ Starts playback.
            Called by the playback control skill to start playback if the
            skill is selected (has the best match level)
        """
        # setup audio service
        self.audio_service = AudioService(self.bus)
        self.audio_service.play(data[phrase])

    def CPS_match_query_phrase(self, phrase):
        """ This method responds whether the skill can play the input phrase.
            The method is invoked by the PlayBackControlSkill.
            Returns: tuple (matched phrase(str),
                            match level(CPSMatchLevel),
                            optional data(dict))
                     or None if no match was found.
        """
        # first thing is connect to emby or bail
        if not self.connect_to_emby():
            return None

        # NEW CODE
        songs = []
        self.log.log(20, "CPS_match_query_phrase() phrase = "+phrase)
        music_info = self.emby_croft.parse_common_phrase(phrase)
        match_type = music_info.match_type
        self.log.log(20, "CPS_match_query_phrase() match_type = "+match_type)
        mesg_file = music_info.mesg_file
        mesg_info = music_info.mesg_info
        songs = music_info.track_uris
        self.log.log(20, "CPS_match_query_phrase() type(songs) = "+str(type(songs)))
        if mesg_file != None:
          self.log.log(20, "CPS_match_query_phrase() mesg_file = "+mesg_file)
          if mesg_info != None:
            self.log.log(20, "CPS_match_query_phrase() mesg_info = "+str(mesg_info))
          self.log.log(20, "CPS_match_query_phrase() calling speak.dialog with wait=True")  
        #  self.speak_dialog(mesg_file, mesg_info, wait=True) # have Mycroft speak the message
          self.speak_dialog(mesg_file, mesg_info) # have Mycroft speak the message
        # END NEW CODE  

        if match_type and songs:
            match_level = None
            if match_type is not None:
                if match_type == 'song' or match_type == 'album':
                    match_level = CPSMatchLevel.TITLE
                    match_level = CPSMatchLevel.EXACT
                elif match_type == 'artist':
                    match_level = CPSMatchLevel.ARTIST
                    match_level = CPSMatchLevel.EXACT
            self.log.log(20, "CPS_match_query_phrase() match level = "+str(match_level))

            song_data = dict()
            song_data[phrase] = songs
            # NEW CODE
            num_songs = len(songs)
            # self.log.log(20, "First 3 item urls returned")
            self.log.log(20, "CPS_match_query_phrase() first "+str(num_songs)+" item urls returned")
            # END NEW CODE
            max_songs_to_log = 3
            songs_logged = 0
            for song in songs:
                self.log.log(20, "CPS_match_query_phrase() song = "+str(song))
                songs_logged = songs_logged + 1
                if songs_logged >= max_songs_to_log:
                    break

            return phrase, match_level, song_data
        else:
            return None

    def connect_to_emby(self, diagnostic=False):
        """
        Attempts to connect to the server based on the config
        if diagnostic is False an attempt to auth is also made
        returns true/false on success/failure respectively

        :return:
        """
        auth_success = False
        try:
            self.emby_croft = EmbyCroft(
                self.settings["hostname"] + ":" + str(self.settings["port"]),
                self.settings["username"], self.settings["password"],
                self.device_id, diagnostic)
            auth_success = True
        except Exception as e:
            self.log.log(20, "connect_to_emby() failed to connect to emby, error: {0}".format(str(e)))

        return auth_success


def create_skill():
    return Emby()
