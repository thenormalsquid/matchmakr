import random
from threading import Thread, Event
from Queue import Queue
import logging
import sys
import time
import os.path
import tornado.auth
import tornado.escape
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.log
import tornado.gen
import tornadoredis

from tornado.escape import to_unicode, json_decode, native_str, json_encode

import settings
from tornado.options import options


c = tornadoredis.Client()
c.connect()


class Counter(object):

    def __init__(self):
        self._progress = 0

    def progress(self):
        """Returns the current progress value"""
        return self._progress

    def set_progress(self, value):
        """Sets the current progress value, passing updates to the thread"""

        value = min(value, 100)
        self._progress += value

b = Counter()


class Application(tornado.web.Application):

    def __init__(self):
        debug = (tornado.options.options.environment == "dev")
        handlers = [
            (r"/", IndexHandler),
            (r"/main", MainHandler),
            (r"/love", ScrapeHandler),
            (r"/thinkingloudly", LoadingHandler),
            (r"/yourmatches", CalculatedHandler),
            (r"/auth/login", AuthLoginHandler),
            (r"/auth/logout", AuthLogoutHandler),
            (r"/privacy", PrivacyHandler),
            (r"/terms", TermsHandler),
        ]
        settings = dict(
            cookie_secret="fdkfadsljdfklsjklad98u32#@RDSAF@#(@*&#jlitjuu#$%i99#@G",
            login_url="/auth/login",
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            xsrf_cookies=True,
            facebook_api_key=options.facebook_api_key,
            facebook_secret=options.facebook_secret,
            ui_modules={
                "Partner": PartnerModule, "Contender": ContenderModule},
            debug=True,
            autoescape=None
        )
        tornado.web.Application.__init__(self, handlers, **settings)

# remove get_likes and use in mainhandler


class IndexHandler(tornado.web.RequestHandler):

    def get(self):
        self.render("index.html")


class BaseHandler(tornado.web.RequestHandler):

    def get_current_user(self):
        user_json = self.get_secure_cookie("fbdemo_user")
        if not user_json:
            return None
        return tornado.escape.json_decode(user_json)

    @tornado.gen.coroutine
    def user_exists(self, curr):
        c = tornadoredis.Client()
        c.connect()
        yield tornado.gen.Task(c.hget, "users:%s" % str(curr["id"]), "name")

class AuthLoginHandler(BaseHandler, tornado.auth.FacebookGraphMixin):

    @tornado.web.asynchronous
    def get(self):
        my_url = (self.request.protocol + "://" + self.request.host +
                  "/auth/login?next=" +
                  tornado.escape.url_escape(self.get_argument("next", "/")))
        if self.get_argument("code", False):
            self.get_authenticated_user(
                redirect_uri=my_url,
                client_id=self.settings["facebook_api_key"],
                client_secret=self.settings["facebook_secret"],
                code=self.get_argument("code"),
                callback=self._on_auth)
            return
        self.authorize_redirect(redirect_uri=my_url,
                                client_id=self.settings["facebook_api_key"],
                                extra_params={"scope": "read_stream, user_about_me,user_interests,friends_activities,friends_birthday,friends_education_history,friends_interests,friends_likes,friends_relationships,friends_relationship_details,friends_religion_politics,friends_subscriptions,friends_events,friends_status friends_about_me, offline_access,read_friendlists,user_likes,user_activities,user_relationships,user_relationship_details, friends_photos,user_photos"})

    def _on_auth(self, user):
        if not user:
            raise tornado.web.HTTPError(500, "Facebook auth failed")
        self.set_secure_cookie("fbdemo_user", tornado.escape.json_encode(user))
        self.redirect(self.get_argument("next", "/"))


class AuthLogoutHandler(BaseHandler, tornado.auth.FacebookGraphMixin):

    def get(self):
        self.clear_cookie("fbdemo_user")
        self.redirect(self.get_argument("next", "/"))


# all user based magic happens here
# separate scrape logic from calculate and render pages
class MainHandler(BaseHandler, tornado.auth.FacebookGraphMixin):

    """
        Version 1 is completed
        Scrapes your likes and your information to help determine eligibility
    """

    @tornado.web.asynchronous
    @tornado.web.authenticated
    @tornado.gen.coroutine
    def get(self):
        pipe = c.pipeline()
        access_token = self.current_user["access_token"]
        logging.info("%s connected" % self.current_user["name"])
        pipe.hexists("users:%s" % self.current_user["id"], "attracted_to")
        pipe.exists("users:%s" % self.current_user["id"])
        pipe.exists("user:%s" % self.current_user["id"])
        attracted_to, user, likes = yield tornado.gen.Task(pipe.execute)
        if user == 0:
            self.facebook_request("/me", self.get_user,
                                  access_token=access_token)

        if likes == 0:
            self.facebook_request("/me", self.get_likes, access_token=self.current_user[
                                  "access_token"], fields="movies.fields(id,name),music.fields(id,name),favorite_athletes,favorite_teams,religion,political,sports,books.fields(id,name),games.fields(id,name),interests.fields(id,name),television.fields(id,name),activities.fields(id,name)")

        if attracted_to == 1:
            self.display(False)
        else:
            self.display(True)

    def get_user(self, d):
        self.make_user(d)

    # render form, or not to render form
    @tornado.web.asynchronous
    def display(self, b):
        self.render("index.html", form=b)

    @tornado.web.asynchronous
    def get_likes(self, d):
        self.parse_likes(d)

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        self.interested_in = self.get_argument('optionsRadios')
        with c.pipeline() as pipe:
            pipe.hset("users:%s" % self.current_user[
                      "id"], "attracted_to", self.interested_in)
            yield tornado.gen.Task(pipe.execute)
        logging.info("updated interested in")
        self.render("index.html", form=False)

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def make_user(self, d):
        print "inside make_user"
        new = {"name": d["name"]}
        if 'interested_in' not in d:
            new["gender"] = d["gender"]
            self.create_user(d, new)
        elif 'gender' not in d:
            new["gender"] = None
            self.create_user(d, new)
        else:
            new["gender"] = d["gender"]
            new["interested_in"] = d["interested_in"]
            self.create_user(d, new)

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def create_user(self, d, n):
        print "inside create_user"
        with c.pipeline() as pipe:
            pipe.hmset("users:%s" % (d["id"]), n)
            yield tornado.gen.Task(pipe.execute)

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def parse_likes(self, d):
        i = d.itervalues()
        with c.pipeline() as pipe:
            for e in i:
                if 'data' in e:
                    for j in e["data"]:
                        pipe.hset("%s" % j["id"], "name", j["name"])
                        pipe.lpush("user:%s" % d["id"], j["id"])
                elif isinstance(e, list):
                    for h in e:
                        pipe.lpush("user:%s" % d["id"], h["id"])
            yield tornado.gen.Task(pipe.execute)


# could technically keep a counter
class ScrapeHandler(BaseHandler, tornado.auth.FacebookGraphMixin):

    """
    Scrapes essentially
    """
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        yield [tornado.gen.Task(self.get_friends), self.get_things()]
        self.redirect("/yourmatches")

    @tornado.gen.coroutine
    def get_things(self):
        yield [ self.facebook_request("/me",self.get_sports, access_token = self.current_user["access_token"], fields="friends.fields(favorite_teams,favorite_athletes,sports)"),
        self.facebook_request("/me",self.get_books_games, access_token = self.current_user["access_token"], fields="friends.fields(games,books)"),
        self.facebook_request("/me",self.get_interests, access_token = self.current_user["access_token"], fields="friends.fields(interests)"),
        self.facebook_request("/me",self.get_music, access_token = self.current_user["access_token"], fields="friends.fields(music)"),
        self.facebook_request("/me", self.get_tv, access_token = self.current_user["access_token"], fields="friends.fields(television)"),
        self.facebook_request("/me", self.get_movies, access_token = self.current_user["access_token"], fields="friends.fields(movies)"),]

    @tornado.gen.coroutine
    def get_sports(self, d):
        self.set_base_data(
            d, "favorite_teams", "favorite_athletes", "sports")

    @tornado.gen.coroutine
    def get_tv(self, d):
        self.set_connect_data(d, "television")

    @tornado.gen.coroutine
    def get_interests(self, d):
        self.set_connect_data(d, "interests")

    @tornado.gen.coroutine
    def get_music(self, d):
        self.set_connect_data(d, "music")

    @tornado.gen.coroutine
    def get_movies(self, d):
        self.set_connect_data(d, "movies")

    @tornado.gen.coroutine
    def get_friends(self):
        res = yield self.facebook_request("/me", self.smack,
                                          access_token=self.current_user["access_token"], fields="friends.fields(id,name,interested_in,relationship_status,gender)")
        self.create_person(res)

    def smack(self, d):
        return d

    @tornado.gen.coroutine
    def get_books_games(self, d):
        self.set_connect_data(res, "games", "books")

    @tornado.gen.coroutine
    def create_person(self, data):
        with c.pipeline() as pipe:
            d = data["friends"]["data"]
            for i in d:
                if "relationship_status" not in i:
                    pipe.hmset("people:%s" % i["id"], i)
                else:
                    rel = i["relationship_status"]
                    if rel == "Married" or rel == "In a Relationship":
                        # adds taken people
                        pipe.hmset("people:%s:%s" % (i["id"], "taken"), i)
                    elif rel == "Single" or rel == "It's Complicated":
                        pipe.hmset("people:%s" % i["id"], i)
            pipe.hset("users:%s" % self.current_user["id"], "f_check", "True")
            yield tornado.gen.Task(pipe.execute)

    @tornado.gen.coroutine
    def set_base_data(self, d, *args):
        pipe = c.pipeline()
        for e in d["friends"]["data"]:
            for key in args:
                if key in e:
                    user_gender = yield tornado.gen.Task(c.hget, "people:%s" % e["id"], "gender")
                    homewreck_gender = yield tornado.gen.Task(c.hget, "people:%s:taken" % e["id"], "gender")
                    if user_gender:
                        for s in e[key]:
                            # print "likes:%s:%s:%s" %(s["id"],user_gender,s["name"])
                            # print "da"
                            pipe.sadd("likes:%s:%s" % (s[
                                      "id"], user_gender), e["id"])
                    elif homewreck_gender:
                        for s in e[key]:
                            pipe.sadd("likes:%s:%s:%s" % (s[
                                      "id"], homewreck_gender, "homewreck"), e["id"])
        yield tornado.gen.Task(pipe.execute)
        b.set_progress(20)

    @tornado.gen.coroutine
    def set_connect_data(self, d, *args):
        pipe = c.pipeline()
        for f in d["friends"]["data"]:
            for key in args:
                if key in f:
                    user_gender = yield tornado.gen.Task(c.hget, "people:%s" % f["id"], "gender")
                    homewreck_gender = yield tornado.gen.Task(c.hget, "people:%s:taken" % f["id"], "gender")
                    if user_gender:
                        for i in f[key]["data"]:
                        # print "likes:%s:%s:%s" %(i["id"],user_gender,i["name"])
                        # print i.keys()
                            if "name" not in i:
                                continue
                            pipe.sadd("likes:%s:%s" % (i[
                                      "id"], user_gender), f["id"])
                    elif homewreck_gender:
                        for i in f[key]["data"]:
                            if "name" not in i:
                                continue
                            pipe.sadd("likes:%s:%s:homewreck" % (
                                i["id"], homewreck_gender), f["id"])
        yield tornado.gen.Task(pipe.execute)
        b.set_progress(20)


class LoadingHandler(BaseHandler, tornado.auth.FacebookGraphMixin):

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        print b.progress()
        self.write("contemplating amount of lasagnas eaten")

    def on_finish(self):
        print "finished get loading"


class CalculatedHandler(BaseHandler, tornado.auth.FacebookGraphMixin):

    @tornado.web.asynchronous
    @tornado.web.authenticated
    @tornado.gen.coroutine
    def get(self):
            # get top 5 people add to rank
        yield [tornado.gen.Task(self.ready_data)]
        yield self.get_scores()

    @tornado.gen.coroutine
    def get_scores(self):
        pipe = c.pipeline()
        d = {}
        # homewrecker person dict
        dh = {}
        cont = {}
        # homewrecker contender
        hcont = {}
        # must have score with single person for this to work
        scores = yield tornado.gen.Task(c.zrevrange, "match:%s" % (self.current_user["id"]), 0, -1, with_scores=False)
        hscores = yield tornado.gen.Task(c.zrevrange, "match:%s:homewreck" % (self.current_user["id"]), 0, -1, with_scores=False)
        try:
            top = scores[0]
            person = yield tornado.gen.Task(c.hgetall, "people:%s" % top)
            likes = yield tornado.gen.Task(c.smembers, "matches:%s:%s" % (top, self.current_user["id"]))
            hlikes = yield tornado.gen.Task(c.smembers, "matches:%s:%s:homewreck" % (top, self.current_user["id"]))
            for i in likes:
                name = yield tornado.gen.Task(c.hget, "%s" % i, "name")
                d[i] = name
            for h in hlikes:
                name = yield tornado.gen.Task(c.hget, "%s" % h, "name")
                dh[h] = name
            if len(scores) > 5:
                for p in scores[1:6]:
                    l = yield tornado.gen.Task(c.smembers, "matches:%s:%s" % (p, self.current_user["id"]))
                    person2 = yield tornado.gen.Task(c.hgetall, "people:%s" % p)
                    cont[p] = person2
                    cont[p]["likes"] = {}
                    for like in l:
                        name2 = yield tornado.gen.Task(c.hget, "%s" % like, "name")
                        cont[p]["likes"][like] = name2
                for j in hscores[0:6]:
                    hl = yield tornado.gen.Task(c.smembers, "matches:%s:%s:homewreck" % (j, self.current_user["id"]))
                    hperson2 = yield tornado.gen.Task(c.hgetall, "people:%s:taken" % j)
                    hcont[j] = hperson2
                    hcont[j]["likes"] = {}
                    for hlike in hl:
                        hname2 = yield tornado.gen.Task(c.hget, "%s" % hlike, "name")
                        hcont[j]["likes"][hlike] = hname2
                self.render(
                    "partner.html", top_match=person, likes=d, contenders=cont, homewreckers=hcont)
            else:
                self.render(
                    "partner.html", top_match=person, likes=d, contenders=None, homewreckers=None)
        except IndexError:
            self.render(
                "partner.html", top_match=None, likes=None, contenders=None, homewreckers=None)


    @tornado.gen.coroutine
    def ready_data(self):
        interest = yield tornado.gen.Task(c.hget, "users:%s" % self.current_user["id"], "attracted_to")
        u_likes = yield tornado.gen.Task(c.lrange, "user:%s" % self.current_user["id"], 0, -1)
        l = []
        hl = []
        pipe = c.pipeline()
        for i in list(u_likes):
            exists = yield tornado.gen.Task(c.exists, "likes:%s:%s" % (i, interest))
            homewreck_exists = yield tornado.gen.Task(c.exists, "likes:%s:%s:homewreck" % (i, interest))
            if exists:
                members = yield tornado.gen.Task(c.smembers, "likes:%s:%s" % (i, interest))
                for m in members:
                    pipe.sadd("matches:%s:%s" % (
                        m, self.current_user["id"]), i)
                    l.append(m)
            elif homewreck_exists:
                members = yield tornado.gen.Task(c.smembers, "likes:%s:%s:homewreck" % (i, interest))
                for m in members:
                    pipe.sadd("matches:%s:%s:homewreck" % (
                        m, self.current_user["id"]), i)
                    hl.append(m)
        yield tornado.gen.Task(pipe.execute)
        self.calculate(l, hl)

    @tornado.gen.coroutine
    def calculate(self, l, hl):
        pipe = c.pipeline()
        for i in l:
            pipe.zadd("match:%s" % self.current_user["id"], l.count(i), i)
        for j in hl:
            pipe.zadd("match:%s:homewreck" %
                      self.current_user["id"],  hl.count(j), j)
        yield tornado.gen.Task(pipe.execute)



class PrivacyHandler(BaseHandler):
    def get(self):
        return self.render("privacy.html")


class TermsHandler(BaseHandler):
    def get(self):
        return self.render("terms.html")


class PartnerModule(tornado.web.UIModule):

    def render(self, top_match):
        return self.render_string("modules/partner.html", top_match=top_match)


class ContenderModule(tornado.web.UIModule):

    def render(self, contenders):
        self.render_string("modules/contender.html", contenders=contenders)


def main():
    tornado.options.parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    logging.info("listening on :%s" % options.port)
    tornado.ioloop.IOLoop.instance().start()


if __name__ == "__main__":
    main()
