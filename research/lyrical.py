"""
Trying out lyrics stuff
http://test.lyricfind.com/api_service/lyric.do?apikey=87c94e1a862dcd6ccb9fe4f4c567
5007&lrckey=338e17628d2c45501a8ef6168a3dc115&territory=US&reqtype=default&trackid=amg:2033&format=lrc
"""

import sys
import urllib2
import os
import json
from pyechonest import song
import math

import echonest.remix.audio as audio
from echonest.remix.action import render, Crossfade
from pyechonest import config
from binheap import BinHeap
from copy import deepcopy
import pyechonest

config.ECHO_NEST_API_KEY = "SKUP2XKX0MRWEOBIE"

DISPLAY_KEY = os.environ.get('LYRICFIND_DISPLAY_API_KEY')
LRC_KEY = os.environ.get('LYRICFIND_LRC_API_KEY')
SEARCH_KEY = os.environ.get('LYRICFIND_SEARCH_API_KEY')
METADATA_KEY = os.environ.get('LYRICFIND_METADATA_API_KEY')

LYRICFIND_DISPLAY_URL = 'http://test.lyricfind.com/api_service/lyric.do'

def get_json(url):
    """

    Given a properly formatted URL for a JSON web API request, return
    a Python JSON object containing the response to that request.
    """
    f = urllib2.urlopen(url)
    response_text = f.read()
    response_data = json.loads(response_text)
    return response_data    

def make_lrc_url(artist,title):
    """
    Given an artist and title, formats the lyricfind api url for json format
    """
    url = 'http://test.lyricfind.com/api_service/lyric.do?apikey=%s&lrckey=%s&territory=US&reqtype=default\
&trackid=artistname:%s,trackname:%s&format=lrc&output=json' %(DISPLAY_KEY,LRC_KEY,
        artist.replace(' ','+'),title.replace(' ','+'))

    return url

def harvest_lyrics(json):
    return json['track']['lyrics']

def harvest_lrc(json):
    return json['track']['lrc']

def split_pars(string):
    return string.split('\r\n\r\n')

def split_words(string):
    return string.split()


def find_repeats(arr):
    repeated = []
    for i in arr:
        if arr.count(i) > 1 and i not in repeated: repeated.append(i)
    return repeated


def get_timestamp(timed_chorus, worded_chorus):
    """Retieves the time stamp of the first chorus in the song. Could modify
    this to be the second (since that is usually the more colorful one."""
    first_line = worded_chorus[0]
    last_line = worded_chorus[-1]
    # print len(worded_chorus)
    i = -1
    candidates = []

    # Saves all the possible start points of the chorus and their indices:
    for line in timed_chorus:
        i += 1
        if line['line'].strip() == first_line.strip():
            candidates.append([i, line])

    # For each candidate, check if index+len(chorus) or index+len(chorus)-1 is
    # the right end line of the chorus. If it is, add it to the candidate.
    for j in candidates:
        try:
            test_line = timed_chorus[j[0]+len(worded_chorus)]
            other_test_line = timed_chorus[j[0]+len(worded_chorus)-1]
        except IndexError:
            pass

        # print test_line, other_test_line
        if test_line['line'].strip() == last_line.strip():
            j += [test_line]
        elif other_test_line['line'].strip() == last_line.strip():
            j += [other_test_line]

    # for i in candidates: print i, '\n'

    # The right candidate will have 3 elements: index, start line and end line.
    # It doesn't matter if there are more than 1 candidates, it will just pick
    # one and assign the start time and end time accordingly.
    for cand in candidates:
        if len(cand) == 3 and cand[2]['milliseconds'] > cand[1]['milliseconds']:
            start_time = cand[1]['milliseconds']
            end_time = cand[2]['milliseconds']

    # returns times in seconds
    return float(start_time)/1000.0, float(end_time)/1000.0

def find_times(bars, start_time, end_time, fade):
    """Finds and returns the indices of the bars that start and end of the 
    chorus. This function works by, keeping track of the scores of the current
    and previous bars. If the current score becomes higher, it means that the
    loop has passed over the right bar, and we save the previous bar's index"""

    startScore, endScore = 10000000, 10000000
    found_first = False

    for i, bar in enumerate(bars):
        if not found_first:
            prevStartScore, startScore = startScore, abs(bar.start - fade - start_time)
            if startScore > prevStartScore: 
                first_bar = i-1
                found_first = True

        prevEndScore, endScore = endScore, abs(bar.start - fade - end_time)
        if endScore > prevEndScore: 
            last_bar = i-1
            break

    return first_bar, last_bar

def get_words(s):
    """ Returns a dictionary of word counts, given a string"""
    d = {}
    s = s.lower()
    for word in s.split():
        d[word] = d.get(word,0) + 1
    return d

def compute_similarity(d1,d2):
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

def find_chorus_freq(split_pars):
    par_freqs = []
    chorus_freqs = []
    chorus = []
    for par in split_pars:
        par_freqs.append(get_words(par))

    for i in range(len(split_pars)):
        for j in range(i+1,len(split_pars)):
            if compute_similarity(par_freqs[j],par_freqs[i]) > 0.9 and split_pars[i] not in chorus:
                chorus.append(split_pars[i])

    for par in chorus:
        chorus_freqs.append(get_words(par))

    for i in range(len(chorus)):
        for j in range(i+1,len(chorus)):
            if compute_similarity(chorus_freqs[j],chorus_freqs[i]) > 0.85:
                chorus.pop(j)

    return chorus

if __name__ == '__main__':
    artist = 'Ed Sheeran'
    song = 'Thinking Out Loud'
    print make_lrc_url(artist,song)
    timestamped_chorus = harvest_lrc(get_json(make_lrc_url(artist, song)))

    # Remove blank spaces between paragraphs from the timestamped chorus
    timestamped_chorus = [i for i in timestamped_chorus if i['line']]

    # Retrieve the lyrics as a list of separate paragraphs
    b = split_pars(harvest_lyrics(get_json(make_lrc_url(artist, song))))

    # Retrieve the chorus as a list of lines and process it
    a = find_chorus_freq(b)
    chorus = '\n'.join(a)
    chorus_split = chorus.split('\r\n')

    # Get the start and end times of the song based on the chorus given
    start, end = get_timestamp(timestamped_chorus, chorus_split)

    # Locate the track and get necessary attributes
    track = audio.LocalAudioFile(song+'.mp3')
    fade = getattr(track.analysis, 'end_of_fade_in')
    bars = getattr(track.analysis, 'bars')

    # Get starting and ending indices of the bars for the chorus
    index_start, index_end = find_times(bars, start, end, fade)

    # Outputs the chorus and a little more
    render(bars[index_start:index_end+8], 'chorus.mp3', True)







