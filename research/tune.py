import urllib2, urllib, os, json, math, pyechonest, sys, argparse

import echonest.remix.audio as audio
from echonest.remix.action import render, Crossfade
from copy import deepcopy

DISPLAY_KEY = os.environ.get('LYRICFIND_DISPLAY_API_KEY')
LRC_KEY = os.environ.get('LYRICFIND_LRC_API_KEY')
SEARCH_KEY = os.environ.get('LYRICFIND_SEARCH_API_KEY')
METADATA_KEY = os.environ.get('LYRICFIND_METADATA_API_KEY')

LYRICFIND_DISPLAY_URL = 'http://test.lyricfind.com/api_service/lyric.do?'

def get_words(aString):
    """ Returns a dictionary of word counts, given a string"""
    freq = {}
    for word in aString.lower().split():
        freq[word] = freq.get(word,0) + 1
    return freq

def compute_similarity(d1, d2):
    """ Computes cosine similarity of the two dictionaries of words. This method was adapted from:
    http://stackoverflow.com/questions/15173225/how-to-calculate-cosine-similarity-given-2-sentence-strings-python"""
    intersection = set(d1.keys()) & set(d2.keys())
    numerator = sum([d1[w] * d2[w] for w in intersection])
    sum1 = sum([d1[w] ** 2 for w in d1.keys()])
    sum2 = sum([d2[w] ** 2 for w in d2.keys()])
    denominator = math.sqrt(sum1) * math.sqrt(sum2)

    if not denominator:
        return 0.0
    else:
        return float(numerator) / denominator

class Tune():
    """Class for one song in the playlist"""

    def __init__(self, path_to_song, name, artist, tempo=None):
        # Set all necessary attributes to allow for fruitful analysis
        self.tune = audio.LocalAudioFile(path_to_song, verbose=False)
        if not tempo:
            self.track = pyechonest.track.track_from_filename(path_to_song)
            self.bpm = getattr(self.track,'tempo')
        else:
            self.bpm = tempo
        self.segments = getattr(self.tune.analysis, 'segments')
        self.bars = getattr(self.tune.analysis, 'bars')
        self.beats = getattr(self.tune.analysis, 'beats')
        self.fade = getattr(self.tune.analysis, 'end_of_fade_in')
        self.songName = name
        self.artist = artist
        # Set further attributes through class methods
        self.find_lyrics()
        self.get_song_map()
        self.chorus_count = len([i for i in self.song_map if i[2] == 'chorus'])

    def find_lyrics(self):
        """Retrieves lyrics and timestamped lyrics for the tune"""
        try: 
            json_response = self.get_json()
            self.lrc = json_response['track']['lrc'] # Get lyrics with timestamps
            self.lyrics = [i['line'] for i in self.lrc] # Get just the words
        except KeyError:
            # print 'Song lyrics could not be processed'
            # sys.exit()
            raise RuntimeError

    def get_json(self):
        """Makes API request to retrieve song's lyrics"""
        artist = self.artist.replace(' ', '+').encode('ascii', 'ignore')
        song_name = self.songName.replace(' ', '+').encode('ascii', 'ignore')
        # print song_name, artist
        end = urllib.urlencode({"apikey": DISPLAY_KEY, "lrckey": LRC_KEY, 
                                "territory": "US", "reqtype": "default",
                                "format": "lrc", "output": "json",
                                "trackid": "artistname:" + artist + ",trackname:" + song_name})
        url = LYRICFIND_DISPLAY_URL + end
        f = urllib2.urlopen(url)
        return json.loads(f.read())

    def get_song_map(self):
        """Returns a list of tuples in the form (start, end, 'verse'/'chorus')
        that linearly maps out the lyrics of the song"""

        # Get all the choruses in the lrc
        choruses = self.find_chorus_freq(self.lyrics)

        # Add each line to chorus_lines
        chorus_lines = []
        for i in choruses:
            if i not in chorus_lines:
                chorus_lines += [j.strip() for j in i.split('\n')]

        verse, chorus, self.song_map = [], [], []
        i = 0

        # Goes through self.lrc line by line. Saves each line in the verse or
        # chorus list, then if blank line (new paragraph) is found empties out
        # the list and save the data in the song_map as a [starttime, endtime, 'chorus'/'verse'] list
        while i < len(self.lrc):
            if self.lrc[i]['line']:
                if self.lrc[i]['line'].strip() in chorus_lines:
                    chorus.append(self.lrc[i]['milliseconds'])
                else:
                    verse.append(self.lrc[i]['milliseconds'])
            if not self.lrc[i]['line'] or i==len(self.lrc)-1:
                if verse:
                    self.song_map.append([int(verse[0]), int(verse[-1]), 'verse'])
                    verse = []
                if chorus:
                    self.song_map.append([int(chorus[0]), int(chorus[-1]), 'chorus'])
                    chorus = []
            i += 1

        self.song_map = sorted([i for i in self.song_map if i[0] != i[1]], key=lambda x:x[0])

        self.song_map = self.group_map(self.song_map)

    def find_chorus_freq(self, split_pars):
        """Finds chorus based off of similar word frequencies"""
        par_freqs = []
        chorus = []

        # print split_pars

        for par in split_pars:
            # print par
            # if 'chorus' in par.split('\n')[0].strip().lower():
            #     if len(par.split('\n')) > 2:
            #         print '[CHORUS]', par.split('\n')[1:]
            #         chorus += par.split('\n')[1:]
            par_freqs.append(get_words(par))

        for i in range(len(split_pars)):
            for j in range(i+1,len(split_pars)):
                if compute_similarity(par_freqs[j],par_freqs[i]) > 0.6 and split_pars[i]:
                    chorus.append(split_pars[i])

        return chorus

    def choose_jump_point(self, position='start'):
        """Attempts to choose the bars of the track by taking the start of one song, and 
        setting the end to be after the 2nd + chorus as long as there is no vocals immediately
        after"""
        self.position = position

        if self.position == 'start':
            return self.find_tail()
        elif self.position == 'end':
            return self.find_start()
        elif self.position == 'middle':
            a = self.find_start()
            b = self.find_tail()
            # print a[0], b[1]
            return a[0], b[1]

    def find_start(self):
        """Finds the part to cut INTO the song from another song.
        Has to be before the verse before the second chorus, because find_tail 
        finds anything after the second chorus.""" 
        chor_count = 0
        i = 0
        if self.chorus_count == 1:
            CHORUS_THRESHOLD = self.chorus_count - 1
        else:
            CHORUS_THRESHOLD = self.chorus_count // 2

        # Filter out self.song_map so that the only parts available are before
        # the second chorus
        available = []
        while chor_count < CHORUS_THRESHOLD and i < len(self.song_map):
            if self.song_map[i][2] == 'chorus':
                chor_count += 1
            if chor_count > CHORUS_THRESHOLD:
                pass
            else:
                available.append(self.song_map[i])
            i += 1

        verse_index = [i for i,j in enumerate(available) if j[2] == 'verse']

        # Find 6 second gap into a verse
        if len(verse_index) <= 1:
            print 'first verse'
            return self.get_bars(self.song_map[0][0], None)
        else:
            for i in verse_index:
                start_verse = available[i][0]
                end_last_section = available[i-1][1]
                if abs(start_verse - end_last_section) >= 4:
                    print 'found one'
                    return self.get_bars(available[i][0], None)


    def find_tail(self):
        """Finds the part of the song to cut OUT OF. Has to be after the second
        chorus."""
        to_play = [0]
        i = 0
        chor_count = 0
        if self.chorus_count == 1:
            CHORUS_THRESHOLD = self.chorus_count - 1
        else:
            CHORUS_THRESHOLD = self.chorus_count // 2

        # Remove sections from the available list up to but not including the 
        # second chorus. Uncomment print statements to see which option the 
        # program went for
        available = deepcopy(self.song_map)

        while chor_count < CHORUS_THRESHOLD:
            if available[0][2] == 'chorus':
                chor_count += 1
            if chor_count <= CHORUS_THRESHOLD:
                available.pop(0)

        print self.song_map
        print available

        chorus_index = [i for i,j in enumerate(available) if j[2] == 'chorus']
        print chorus_index

        if len(chorus_index) == 1:
            print 'first chorus'
            return self.get_bars(0, available[chorus_index[0]][1])
        else:
            for i in chorus_index:
                end_chorus = available[i][1]
                try: 
                    start_next_section = available[i+1][0]
                    if abs(start_next_section - end_chorus) >= 4:
                        print 'found one'
                        return self.get_bars(available[i][0], None)
                except IndexError: pass 

    def group_map(self, oldmap):
        newmap = []
        i = 0

        while i < len(oldmap):
            start = oldmap[i][0]/1000.0
            current_section = oldmap[i][2]
            try:
                while oldmap[i+1][2] == current_section:
                    i += 1
            except IndexError: pass
            end = oldmap[i][1]/1000.0
            assert(oldmap[i][2] == current_section)
            newmap.append([start, end, current_section])
            i += 1

        print oldmap
        print newmap

        return newmap
 
    def find_chorus_bars(self):
        """Finds and returns the start and end bars of each chorus found in the
        song map"""
        all_chorus = []
        choruses = [i for i in self.song_map if i[2] == 'chorus']
        
        all_chorus = self.group_map(choruses)

        # print choruses
        # print all_chorus

        for j in range(len(all_chorus)):
            all_chorus[j] = self.get_bars(all_chorus[j][0], all_chorus[j][1])

        # Returns only choruses that are longer than four bars (other results
        # are anomalies)
        return [i for i in all_chorus if i[1] - i[0] > 4]

    def get_bars(self, start_time, end_time=None):
        """Finds and returns the indices of the bars that start and end of the 
        chorus. This function works by, keeping track of the scores of the current
        and previous bars. If the current score becomes higher, it means that the
        loop has passed over the right bar, and we save the previous bar's index"""

        startScore, endScore = 10000000, 10000000
        first_bar = 0
        last_bar = len(self.bars)-1
        found_first = False

        for i, bar in enumerate(self.bars):
            if not found_first:
                prevStartScore, startScore = startScore, abs(bar.start - self.fade - start_time)
                if startScore > prevStartScore: 
                    first_bar = i-1
                    found_first = True

            if end_time:
                prevEndScore, endScore = endScore, abs(bar.start - self.fade - end_time)
                if endScore > prevEndScore: 
                    last_bar = i-1
                    break

        if end_time:
            return first_bar, last_bar
        else:
            return first_bar, len(self.bars)-1

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('artist', help='Enter the artist(s) of your song')
    parser.add_argument('songName', help='Enter the name of your song')
    parser.add_argument('fileName', help='Enter the file name of your song')
    args = parser.parse_args()

    # bs = Tune(args.fileName, args.songName, args.artist, 86)
    # bars = bs.find_chorus_bars()

    # for i in range(len(bars)):
    #     render(bs.bars[max(0,bars[i][0]-1):bars[i][1]+2], str(i+1)+'chorus.mp3', True)


    bs = Tune(args.fileName, args.songName, args.artist)
    # print bs.song_map
    # for i in bs.lrc: print i
    # print bs.song_map
    # bars = bs.find_chorus_bars()
    # bars = bs.choose_jump_point(position='start')

    # # print bars
    # print bs.bars[0].start, 'time'
    # render(bs.bars[bars[0]:bars[1]+1], 'play.mp3', True)
    # for i in range(len(bars)):
    #     render(bs.bars[max(0,bars[i][0]-1):bars[i][1]+2], str(i+1)+'chorus.mp3', True)
