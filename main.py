import datetime
import logging
import os
import re
from urllib2 import quote

from google.appengine.api import images, urlfetch
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

from django.utils import simplejson
from webob import _parse_date

import oauth
import secrets


class CTzinfo(datetime.tzinfo):
    def utcoffset(self, dt): return datetime.timedelta(hours=-7)
    def dst(self, dt): return datetime.timedelta(hours=-6)
    def tzname(self, dt): return 'PDT'

class ChartAPIException(Exception):
    def __init__(self, response):
        super(ChartAPIException, self) \
            .__init__("Google chart API error %d" % response.status_code)
        self.response = response

def chart_img(url):
    logging.debug("Chart API request %r" % url)
    rs = urlfetch.fetch(url, deadline=10)
    if rs.status_code == 200:
        return rs.content
    else:
        raise ChartAPIException(rs)


class AuthHandler(webapp.RequestHandler):
    def get(self):
        client = oauth.TwitterClient(secrets.CONSUMER_KEY,
                                     secrets.CONSUMER_SECRET,
                                     'http://%s/callback/' % os.environ['SERVER_NAME'])
        self.redirect(client.get_authorization_url())


class CallbackHandler(webapp.RequestHandler):
    def get(self):
        client = oauth.TwitterClient(secrets.CONSUMER_KEY, secrets.CONSUMER_SECRET,
                                     'http://%s/callback/' % os.environ['SERVER_NAME'])
        auth_token = self.request.get('oauth_token')
        auth_verifier = self.request.get('oauth_verifier')
        user_info = client.get_user_info(auth_token, auth_verifier=auth_verifier)
        logging.debug("user_info: %r" % (user_info,))


class ServeHandler(webapp.RequestHandler):

    def error_msg(self, code, msg):
        super(ServeHandler, self).error(code)
        self.response.out.write(msg)

    def get(self, tweet_id):
        try:
            self._gen_shot(int(tweet_id))
        except ChartAPIException, e:
            self.error_msg(500, e.message)

    def _gen_shot(self, tweet_id):
        client = oauth.TwitterClient(secrets.CONSUMER_KEY,
                                     secrets.CONSUMER_SECRET,
                                     'http://%s/callback/' % os.environ['SERVER_NAME'])

        tweet_rs = client.make_request(
            'http://api.twitter.com/1/statuses/show/%d.json' % tweet_id,
            token=secrets.CLIENT_TOKEN,
            secret=secrets.CLIENT_SECRET)

        if tweet_rs.status_code != 200:
            self.error_msg(500, "Twitter API error %d: %s" % (tweet_rs.status_code, tweet_rs.content))
            return

        # Twitter API encodes utf-8
        assert 'utf-8' in tweet_rs.headers['Content-Type']

        # Parse tweet
        tweet = simplejson.loads(tweet_rs.content)
        text = tweet.get('text')
        if not text:
            self.error_msg(404, "No tweet text")
            return

        user = tweet.get('user') or {}
        bg_rpc = prof_rpc = None
        bg = user.get('profile_background_image_url', None)
        if bg:
            bg_rpc = urlfetch.create_rpc()
            urlfetch.make_fetch_call(bg_rpc, bg)
            logging.debug("Loading background from %r" % bg)
        profile = user.get('profile_image_url', None)
        if profile:
            prof_rpc = urlfetch.create_rpc()
            urlfetch.make_fetch_call(prof_rpc, profile)
            logging.debug("Loading profile picture from %r" % profile)

        words = text.encode('utf-8').split()
        line_imgs = []

        # Generate Google chart text boxes for all text, one for each line
        # (I want to adjust the line height)
        while words:
            logging.debug("Words left: %r" % words)
            r = (1, len(words))
            mid = r[1]
            line_img = None

            # Here we do a binary search to find how many of the words
            # we can fit into one line.
            while True:

                logging.debug("Requesting [%d,%d,%d]" % (r[0], mid, r[1]))

                line = None                
                try:
                    line = chart_img('http://chart.apis.google.com/chart?'
                                     'chst=d_text_outline&chld=000000|24|l|f7f7f7|_|%s'
                                     '&chf=bg,s,ffffff' % quote(' '.join(words[0:mid])))
                except ChartAPIException, e:
                    if e.response.status_code != 400:
                        raise
                    # Otherwise text was probably just too wide

                # 600px wide, 25px margin
                if not line or images.Image(line).width > 550:
                    r = (r[0], mid)
                else:
                    r = (mid, r[1])
                    line_img = line

                mid = max(1, r[0] + (r[1] - r[0]) / 2)
                if mid == r[0] and line_img:
                    break

            line_imgs.append(line_img)
            words = words[mid:]

        # Generate date string

        created = _parse_date(tweet['created_at']).astimezone(CTzinfo())
        created = filter(lambda s: s,
                         (created.strftime(fmt).lstrip('0')
                          for fmt in ('%a %b', '%d', '%I:%M%p %Y', '%Z')))
        created_str = ' '.join(created)
        source = tweet.get('source')
        if source:
            # Yea, can't re HTML but let's try
            source = re.sub('<[^>]*>', '', source)
            created_str += ' via %s' % source
        place = tweet.get('place')
        place = place and place.get('full_name')
        if place:
            created_str += ' from %s' % place
        reply_to = tweet.get('in_reply_to_screen_name')
        if reply_to:
            created_str += ' in reply to %s' % reply_to

        # Generate some more charts...
        created = chart_img('http://chart.apis.google.com/chart?'
                            'chst=d_text_outline&chld=b0b0b0|10|l|ffffff|_|%s'
                            '&chf=bg,s,ffffff' % quote(created_str))

        screen_name = chart_img('http://chart.apis.google.com/chart?'
                                'chst=d_text_outline&chld=0000ff|24|l|ffffff|_|%s'
                                '&chf=bg,s,ffffff' % quote(user.get('screen_name', '')))

        name = chart_img('http://chart.apis.google.com/chart?'
                         'chst=d_text_outline&chld=000000|13|l|ffffff|_|%s'
                         '&chf=bg,s,ffffff' % quote(user.get('name', '')))

        # Start generating the actual tweetshot

        MARGIN, PADDING, LINE = 50, 25, 30
        MARGINF, PADDINGF, LINEF = map(float, (MARGIN, PADDING, LINE))
        lines = len(line_imgs)

        tmpl_data = open('tweet-bg.png', 'rb').read()
        tmpl = images.Image(tmpl_data)
        t_width, t_height = tmpl.width, tmpl.height
        width, height = t_width + 2 * MARGIN, t_height + 2 * MARGIN + (lines - 1) * LINE

        # Damn the rounded corners; need to seriously slice and re-compose

        px3 = 3. / t_width
        top1 = images.crop(tmpl_data,
                           px3,
                           0.,
                           1. - px3,
                           PADDINGF / t_height)
        top2 = images.crop(tmpl_data,
                           0.,
                           3. / t_height,
                           1.,
                           PADDINGF / t_height)

        line_bg = images.crop(tmpl_data, 0., PADDINGF / t_height, 1., (PADDINGF + LINE) / t_height)

        bottom1 = images.crop(tmpl_data,
                              px3,
                              (PADDINGF + LINE) / t_height,
                              1 - px3,
                              1.)
        bottom2 = images.crop(tmpl_data,
                              0.,
                              (PADDINGF + LINE) / t_height,
                              1.,
                              1 - 3. / t_height)

        # Okay, let's start composing the image

        # Layout background to bottom

        components = []

        bg_rs = bg_rpc and bg_rpc.get_result()
        if bg_rs:
            if bg_rs.status_code == 200:
                bg_img = images.Image(bg_rs.content)
                components += [(bg_rs.content, x, y, 1., images.TOP_LEFT)
                               for x in range(0, width, bg_img.width)
                               for y in range(0, height, bg_img.height)]
            else:
                logging.warning("Background download failed %d: %r"
                                % (bg_rs.status_code, bg_rs.content))

        # Then add tweet box and texts

        footer_y = MARGIN + PADDING + lines * LINE

        components += [(top1, MARGIN + 3, MARGIN, 1., images.TOP_LEFT),
                       (top2, MARGIN, MARGIN + 3, 1., images.TOP_LEFT)] \
                      + [(line_bg, MARGIN, MARGIN + PADDING + n * LINE, 1., images.TOP_LEFT)
                         for n in range(len(line_imgs))] \
                      + [(bottom1, MARGIN + 3, footer_y, 1., images.TOP_LEFT),
                         (bottom2, MARGIN, footer_y, 1., images.TOP_LEFT)] \
                      + [(line, MARGIN + PADDING, MARGIN + PADDING + n * LINE, 1., images.TOP_LEFT)
                         for n, line in enumerate(line_imgs)] \
                      + [(created, MARGIN + PADDING, footer_y + 3, 1., images.TOP_LEFT),
                         (screen_name, MARGIN + PADDING + 48 + 20, footer_y + 49, 1., images.TOP_LEFT),
                         (name, MARGIN + PADDING + 48 + 20, footer_y + 49 + 26, 1., images.TOP_LEFT)]

        # Add profile picture

        prof_rs = prof_rpc and prof_rpc.get_result()
        prof_pic = None
        if prof_rs:
            if prof_rs.status_code == 200:
                prof_pic = images.Image(prof_rs.content)
                if not (prof_pic.width == prof_pic.height == 48):
                    prof_pic = images.resize(prof_rs.content, 48, 48)
                components.append((prof_pic, MARGIN + PADDING, footer_y + 48, 1., images.TOP_LEFT))
            else:
                logging.warning("Profile picture download failed %d: %r"
                                % (prof_rs.status_code, prof_rs.content))

        pix = open('pix.png', 'rb').read()

        def _corners():
            yield (lambda x: MARGIN + x), (lambda y: MARGIN + y)
            yield (lambda x: width - MARGIN - x - 1), (lambda y: MARGIN + y)
            yield (lambda x: MARGIN + x), (lambda y: height - MARGIN - y - 1)
            yield (lambda x: width - MARGIN - x - 1), (lambda y: height - MARGIN - y - 1)

        # Insert magic corner dust
        components += reduce(lambda pixies, (fx, fy):
                                 pixies + [(pix, fx(x), fy(y), a, images.TOP_LEFT)
                                           for x, y, a in ((1, 1, .8), (2, 0, .5), (0, 2, .5),
                                                           (2, 1, 1.), (2, 2, 1.), (1, 2, 1.))],
                             _corners(),
                             [])

        tweetshot = components.pop(0)
        while components:
            batch, components = components[:15], components[15:]
            tweetshot = (images.composite([tweetshot] + batch, width, height),
                         0, 0, 1., images.TOP_LEFT)

        self.response.headers['Content-Type'] = 'image/png'
        self.response.headers['Cache-Control'] = 'max-age=%d' % (24 * 60 * 60)
        self.response.out.write(tweetshot[0])


def main():
    application = webapp.WSGIApplication([
          ('/(\d+)\.png', ServeHandler),
          ('/auth/', AuthHandler),
          ('/callback/', CallbackHandler),
          ], debug=True)
    run_wsgi_app(application)

if __name__ == '__main__':
    main()
