
from couchpotato.core.event import addEvent, fireEvent
from couchpotato.core.helpers.rss import RSS
from couchpotato.core.logger import CPLog
from couchpotato.core.providers.base import NZBProvider
from couchpotato.environment import Env
from dateutil.parser import parse
from urllib import urlencode
from urllib2 import URLError
import httplib
import time
import traceback
import urllib
import xml.etree.ElementTree as XMLTree

log = CPLog(__name__)


class Newzbin(NZBProvider, RSS):
    searchUrl = 'https://www.newzbin.com/search/'

    format_ids = {
        2: ['scr'],
        1: ['cam'],
        4: ['tc'],
        8: ['ts'],
        1024: ['r5'],
    }
    cat_ids = [
        ([2097152], ['1080p']),
        ([524288], ['720p']),
        ([262144], ['brrip']),
        ([2], ['dvdr']),
    ]
    cat_backup_id = -1

    def search(self, movie, quality):

        results = []
        if self.isDisabled() or not self.isAvailable(self.searchUrl):
            return results

        format_id = self.getFormatId(type)
        cat_id = self.getCatId(type)

        arguments = urlencode({
            'searchaction': 'Search',
            'u_url_posts_only': '0',
            'u_show_passworded': '0',
            'q_url': 'imdb.com/title/' + movie['library']['identifier'],
            'sort': 'ps_totalsize',
            'order': 'asc',
            'u_post_results_amt': '100',
            'feed': 'rss',
            'category': '6',
            'ps_rb_video_format': str(cat_id),
            'ps_rb_source': str(format_id),
        })

        url = "%s?%s" % (self.searchUrl, arguments)
        cache_key = str('newzbin.%s.%s.%s' % (movie['library']['identifier'], str(format_id), str(cat_id)))
        single_cat = True

        try:
            data = self.getCache(cache_key)
            if not data:
                data = self.urlopen(url, username = self.conf('username'), password = self.conf('password'))
                self.setCache(cache_key, data)
        except (IOError, URLError):
            log.error('Failed to open %s.' % url)
            return results

        if data:
            try:
                try:
                    data = XMLTree.fromstring(data)
                    nzbs = self.getElements(data, 'channel/item')
                except Exception, e:
                    log.debug('%s, %s' % (self.getName(), e))
                    return results

                for nzb in nzbs:

                    title = self.getTextElement(nzb, "title")
                    if 'error' in title.lower(): continue

                    REPORT_NS = 'http://www.newzbin.com/DTD/2007/feeds/report/';

                    # Add attributes to name
                    for attr in nzb.find('{%s}attributes' % REPORT_NS):
                        title += ' ' + attr.text

                    id = int(self.getTextElement(nzb, '{%s}id' % REPORT_NS))
                    size = str(int(self.getTextElement(nzb, '{%s}size' % REPORT_NS)) / 1024 / 1024) + ' mb'
                    date = str(self.getTextElement(nzb, '{%s}postdate' % REPORT_NS))

                    new = {
                        'id': id,
                        'type': 'nzb',
                        'name': title,
                        'age': self.calculateAge(int(time.mktime(parse(date).timetuple()))),
                        'size': self.parseSize(size),
                        'url': str(self.getTextElement(nzb, '{%s}nzb' % REPORT_NS)),
                        'download': lambda: self.download(id),
                        'detail_url': str(self.getTextElement(nzb, 'link')),
                        'description': self.getTextElement(nzb, "description"),
                        'check_nzb': False,
                    }
                    new['score'] = fireEvent('score.calculate', new, movie, single = True)

                    is_correct_movie = fireEvent('searcher.correct_movie',
                                                 nzb = new, movie = movie, quality = quality,
                                                 imdb_results = True, single_category = single_cat, single = True)
                    if is_correct_movie:
                        results.append(new)
                        self.found(new)

                return results
            except SyntaxError:
                log.error('Failed to parse XML response from newzbin.com')

        return results

    def download(self, nzb_id):

        try:
            conn = httplib.HTTPSConnection('www.newzbin.com')

            postdata = { 'username': self.conf('username'), 'password': self.conf('password'), 'reportid': nzb_id }
            postdata = urllib.urlencode(postdata)

            headers = {
                'User-agent': 'CouchPotato+/%s' % Env.get('version'),
                'Content-type': 'application/x-www-form-urlencoded',
            }

            fetchurl = '/api/dnzb/'
            conn.request('POST', fetchurl, postdata, headers)
            response = conn.getresponse()

            # Save debug info if we have to
            data = response.read()

        except:
            log.error('Problem with Newzbin server: %s' % traceback.format_exc())
            return False

        # Is a valid response
        return_code = response.getheader('X-DNZB-RCode')
        return_text = response.getheader('X-DNZB-RText')

        if return_code is not '200':
            log.error('Error getting nzb from Newzbin: %s, %s' % (return_code, return_text))
            return False

        return data

    def getFormatId(self, format):
        for id, quality in self.format_ids.iteritems():
            for q in quality:
                if q == format:
                    return id

        return self.cat_backup_id

    def isEnabled(self):
        return NZBProvider.isEnabled(self) and self.conf('enabled') and self.conf('username') and self.conf('password')
