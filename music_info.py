class Music_info:
  match_type = ""                  # album, artist or song
  mesg_file = ""                   # if mycroft has to speak first
  mesg_info = {}                   # values to plug in
  track_uris = []                  # list of URIs to play
  def __init__(self, match_type, mesg_file, mesg_info, track_uris):
    self.match_type = match_type
    self.mesg_file = mesg_file
    self.mesg_info = mesg_info
    self.track_uris = track_uris 