I did this very quick and dirty hack to get tweets to png. Mainly motivated
by the Github wiki's restrictions of what can be embedded there.

But it works! (If you see a rendering below...)

![Some tweet](http://tweetpng.appspot.com/23019320509-500.png)

See it in action at [tweetpng.appspot.com](http://tweetpng.appspot.com/)

Replace the id on the url with any tweet id and (if you're lucky) you'll get
a nice png.

Implementation note: Renders texts with [Google Chart API](http://code.google.com/apis/chart/docs/gallery/dynamic_icons.html#outlined_text)

### FORKERS

You need to create a `secrets.py` like
    CONSUMER_KEY = "GQlpCF6b.."
    CONSUMER_SECRET = ".."
    CLIENT_TOKEN = "1525313.."
    CLIENT_SECRET = ".."

1. [Create an OAuth consumer](http://twitter.com/oauth_clients), return url `http://<appid>.appspot.com/callback/`
1. Paste consumer keys to `secrets.py`
1. Goto `http://<appid>.appspot.com/auth/` and Allow
1. Copy-paste client keys from url to `secrets.py`

Then you should be all set...

For details, see [Nick's blog](http://blog.notdot.net/2010/02/Writing-a-twitter-service-on-App-Engine).

### TODO

1. Optimize splitting of long words (URLs, chinese) with binary search. Binary splitting is currently done only on word level, not character.
