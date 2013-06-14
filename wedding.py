import ast
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
#non-blocking redis
import tornadoredis
import settings
from tornado.options import options

import simplejson as json

#global redis client class
redis = tornadoredis.Client()
redis.connect()

pipe = redis.pipeline()

class Application(tornado.web.Application):

    def __init__(self):
        debug = (tornado.options.options.environment == "dev")
        handlers = [
            (r"/", IndexHandler),
            (r"/main", MainHandler),
            (r"/love", ScrapeHandler),
            (r"/thinkingloudly", LoadingHandler),
            (r"/mymatches", CalculatedHandler),
            (r"/auth/login", AuthLoginHandler),
            (r"/auth/logout", AuthLogoutHandler),
            (r"/privacy", PrivacyHandler),
            (r"/batch", BatchHandler),
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
        logging.info(self.request.headers)
        self.render("index.html")


class ExceptionHandler(tornado.web.RequestHandler):

     def __init__(self, application, request, status_code):
        tornado.web.RequestHandler.__init__(self, application, request)
        self.set_status(status_code)

     def get_error_html(self, status_code, **kwargs):
        self.require_setting("static_path")
        if status_code in [404, 500, 503, 403]:
            self.render("oops.html", status_code=status_code)
        logging.error( {"code": status_code,"message": status_code})
        logging.info(self.request.headers)

     def get_error_scraping(self, status_code, **kwargs):
        self.require_setting("static_path")
        if status_code == 599:
            self.redirect("/mymatches")
        logging.error({"code":status_code})

     def prepare(self):
        raise tornado.web.HTTPError(self._status_code)



class BaseHandler(tornado.web.RequestHandler):

    def get_current_user(self):
        """
        This method is called whenever the self.current_user property is not
        already cached. See tornado/web.py RequestHandler.current_user.
        """

        user_json = self.get_secure_cookie("fbdemo_user")
        if not user_json:
            return None
        return tornado.escape.json_decode(user_json)

    @tornado.gen.coroutine
    def user_exists(self, curr):
        yield tornado.gen.Task(redis.hget, "users:%s" % str(curr["id"]), "name")

class AuthLoginHandler(BaseHandler, tornado.auth.FacebookGraphMixin):

    @tornado.web.asynchronous
    def get(self):
        my_url = (self.request.protocol + "://" + self.request.host +
                  "/auth/login?next=" +
                  tornado.escape.url_escape(self.get_argument("next", "/")))
        logging.info(self.request.headers)
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
        logging.info("%s disconnected", self.current_user["name"])
        logging.info(self.request.headers)
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
        pipe = redis.pipeline()
        access_token = self.current_user["access_token"]
        logging.info("%s connected" % self.current_user["name"])
        logging.info(self.request.headers)
        pipe.hexists("users:%s" % self.current_user["id"], "attracted_to")
        pipe.exists("users:%s" % self.current_user["id"])
        pipe.exists("user:%s" % self.current_user["id"])
        try:
            attraction_known, user_exists, likes_exist = yield tornado.gen.Task(pipe.execute)
            token = self.current_user["access_token"]

            if not user_exists:
                logging.debug("getting user info from Facebook")
                self.facebook_request("/me", self.get_user, access_token=token)

            fb_like_fields = (
                "movies.fields(id,name),music.fields(id,name),"
                "favorite_athletes,favorite_teams,religion,political,sports,"
                "books.fields(id,name),games.fields(id,name),"
                "interests.fields(id,name),television.fields(id,name),"
                "activities.fields(id,name),religion,education,political"
            )

            if not likes_exist:
                logging.debug("getting user likes from Facebook")
                self.facebook_request("/me", self.get_likes, access_token=token,
                                      fields=fb_like_fields)

            if not attraction_known:
                logging.debug("prompting user for gender attraction")
                self.render("index.html", show_form=True)
            else:
                self.render("index.html", show_form=False)

        except ValueError:
            logging.error("too many values to unpack")
            self.redirect("/main")


    def get_user(self, d):
        self.make_user(d)

    @tornado.web.asynchronous
    def get_likes(self, d):
        self.parse_likes(d)

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        self.interested_in = self.get_argument('optionsRadios')
        with redis.pipeline() as pipe:
            pipe.hset("users:%s" % self.current_user[
                      "id"], "attracted_to", self.interested_in)
            yield tornado.gen.Task(pipe.execute)
        logging.info("updated interested in")
        self.render("index.html", show_form=False)

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def make_user(self, data):
        print "inside make_user"

        new_user = { "name": data["name"] }
        if 'interested_in' not in data:
            new_user["gender"] = data["gender"]
        elif 'gender' not in data:
            new_user["gender"] = None
        else:
            new_user["gender"] = data["gender"]
            new_user["interested_in"] = data["interested_in"]

        with redis.pipeline() as pipe:
            pipe.hmset("users:%s" % data["id"], new_user)
            yield tornado.gen.Task(pipe.execute)

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def parse_likes(self, d):
        pipe = redis.pipeline()
        for item in d.iteritems():
            #item is a tuple
            #item[0] is the category keyword
            if 'data' in item[1]:
                for like in item[1]["data"]:
                    #print like["id"], like["name"]
                    pipe.hset(like["id"], "name", like["name"])
                    pipe.sadd("%s:%s" % (item[0],d["id"]),like["id"])
        yield tornado.gen.Task(pipe.execute)


# could technically keep a counter
class ScrapeHandler(BaseHandler, tornado.auth.FacebookGraphMixin):

    """
    Scrapes essentially Going to be deprecated
    """
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        yield [tornado.gen.Task(self.get_friends), self.get_things()]
        self.redirect("/mymatches")

    @tornado.gen.coroutine
    def get_things(self):
        yield [ self.facebook_request("/me",self.get_sports, access_token = self.current_user["access_token"], fields="friends.fields(favorite_teams,favorite_athletes,sports)"),
        self.facebook_request("/me",self.get_games, access_token = self.current_user["access_token"], fields="friends.fields(games)"),
        self.facebook_request("/me",self.get_interests, access_token = self.current_user["access_token"], fields="friends.fields(interests)"),                
        self.facebook_request("/me", self.get_tv, access_token = self.current_user["access_token"], fields="friends.fields(television)"),
        self.facebook_request("/me", self.get_movies, access_token = self.current_user["access_token"], fields="friends.fields(movies)"),
        self.facebook_request("/me", self.get_books,access_token = self.current_user["access_token"], fields="friends.fields(books)")]
        try:
            print "hi"
            self.facebook_request("/me",self.get_music, access_token = self.current_user["access_token"], fields="friends.fields(music)")
        except HTTPError:
            self.redirect("/mymatches")

    @tornado.gen.coroutine
    def get_sports(self, d):
        res = d
        self.set_base_data(
            res, "favorite_teams", "favorite_athletes", "sports")

    @tornado.gen.coroutine
    def get_tv(self, d):
        res = d
        self.set_connect_data(res, "television")

    @tornado.gen.coroutine
    def get_interests(self, d):
        res = d
        self.set_connect_data(res, "interests")

    @tornado.gen.coroutine
    def get_music(self, d):
        res = d
        self.set_connect_data(res, "music")

    @tornado.gen.coroutine
    def get_movies(self, d):
        res = d
        self.set_connect_data(res, "movies")

    @tornado.gen.coroutine
    def get_friends(self):
        res = yield self.facebook_request("/me", self.smack,
                                          access_token=self.current_user["access_token"], fields="friends.fields(id,name,interested_in,relationship_status,gender)")
        self.create_person(res)

    def smack(self, d):
        return d

    @tornado.gen.coroutine
    def get_games(self, d):
        self.set_connect_data(res, "games")

    @tornado.gen.coroutine
    def get_books(self, d):
        print "lo"
        res = d
        self.set_connect_data(res, "books")

    @tornado.gen.coroutine
    def create_person(self, data):
        with redis.pipeline() as pipe:
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
        pipe = redis.pipeline()
        for e in d["friends"]["data"]:
            for key in args:
                if key in e:
                    user_gender = yield tornado.gen.Task(redis.hget, "people:%s" % e["id"], "gender")
                    homewreck_gender = yield tornado.gen.Task(redis.hget, "people:%s:taken" % e["id"], "gender")
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

    @tornado.gen.coroutine
    def set_connect_data(self, d, *args):
        pipe = redis.pipeline()
        for f in d["friends"]["data"]:
            for key in args:
                if key in f:
                    user_gender = yield tornado.gen.Task(redis.hget, "people:%s" % f["id"], "gender")
                    homewreck_gender = yield tornado.gen.Task(redis.hget, "people:%s:taken" % f["id"], "gender")
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


class LoadingHandler(BaseHandler, tornado.auth.FacebookGraphMixin):

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
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
        pipe = redis.pipeline()
        # top match dict
        # homewrecker person dict
        dh = {}
        cont = {}
        # homewrecker contender
        hcont = {}
        # must have score with single person for this to work
        scores = yield tornado.gen.Task(redis.zrevrange, "match:%s" % (self.current_user["id"]), 0, -1, with_scores=False)
        hscores = yield tornado.gen.Task(redis.zrevrange, "match:%s:homewreck" % (self.current_user["id"]), 0, -1, with_scores=False)
        try:
            top = scores[0]
            person = yield tornado.gen.Task(redis.hgetall, "people:%s" % top)
            likes = yield tornado.gen.Task(redis.smembers, "matches:%s:%s" % (top, self.current_user["id"]))
            hlikes = yield tornado.gen.Task(redis.smembers, "matches:%s:%s:homewreck" % (top, self.current_user["id"]))
            top_match = person
            top_match["likes"] = {}
            for i in likes:
                name = yield tornado.gen.Task(redis.hget, "%s" % i, "name")
                top_match["likes"][i] = name
            for h in hlikes:
                name = yield tornado.gen.Task(redis.hget, "%s" % h, "name")
                dh[h] = name
            if len(scores) > 5:
                for p in scores[1:]:
                    l = yield tornado.gen.Task(redis.smembers, "matches:%s:%s" % (p, self.current_user["id"]))
                    person2 = yield tornado.gen.Task(redis.hgetall, "people:%s" % p)
                    cont[p] = person2
                    cont[p]["likes"] = {}
                    for like in l:
                        name2 = yield tornado.gen.Task(redis.hget, "%s" % like, "name")
                        cont[p]["likes"][like] = name2
                for j in hscores[0:6]:
                    hl = yield tornado.gen.Task(redis.smembers, "matches:%s:%s:homewreck" % (j, self.current_user["id"]))
                    hperson2 = yield tornado.gen.Task(redis.hgetall, "people:%s:taken" % j)
                    hcont[j] = hperson2
                    hcont[j]["likes"] = {}
                    for hlike in hl:
                        hname2 = yield tornado.gen.Task(redis.hget, "%s" % hlike, "name")
                        hcont[j]["likes"][hlike] = hname3
                self.render(
                    "partner.html", top_match=top_match, contenders=cont, homewreckers=hcont)
            else:
                self.render(
                    "partner.html", top_match=top_match, contenders=None, homewreckers=None)
        except IndexError:
            self.render(
                "partner.html", top_match=None, likes=None, contenders=None, homewreckers=None)


    @tornado.gen.coroutine
    def ready_data(self):
        interest = yield tornado.gen.Task(redis.hget, "users:%s" % self.current_user["id"], "attracted_to")
        u_likes = yield tornado.gen.Task(redis.lrange, "user:%s" % self.current_user["id"], 0, -1)
        l = []
        hl = []
        pipe = redis.pipeline()
        for i in list(u_likes):
            exists = yield tornado.gen.Task(redis.exists, "likes:%s:%s" % (i, interest))
            homewreck_exists = yield tornado.gen.Task(redis.exists, "likes:%s:%s:homewreck" % (i, interest))
            if exists:
                members = yield tornado.gen.Task(redis.smembers, "likes:%s:%s" % (i, interest))
                for m in members:
                    pipe.sadd("matches:%s:%s" % (
                        m, self.current_user["id"]), i)
                    l.append(m)
            elif homewreck_exists:
                members = yield tornado.gen.Task(redis.smembers, "likes:%s:%s:homewreck" % (i, interest))
                for m in members:
                    pipe.sadd("matches:%s:%s:homewreck" % (
                        m, self.current_user["id"]), i)
                    hl.append(m)
        yield tornado.gen.Task(pipe.execute)
        self.calculate(l, hl)


    @tornado.gen.coroutine
    def calculate(self, l, hl):
        pipe = redis.pipeline()
        for i in l:
            pipe.zadd("match:%s" % self.current_user["id"], l.count(i), i)
        for j in hl:
            pipe.zadd("match:%s:homewreck" %
                      self.current_user["id"],  hl.count(j), j)
        yield tornado.gen.Task(pipe.execute)



class BatchHandler(BaseHandler, tornado.auth.FacebookGraphMixin):
    """
        This handler stores data, not retrieve
    """
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        res = yield self.facebook_request("/me", self.create_person,
                                          access_token=self.current_user["access_token"], fields="friends.fields(id,name,interested_in,relationship_status,gender,birthday)")
        #self.create_person(res)
        yield self.friendlist(res)
        #me = yield self.facebook_request("", post_args={'batch':[{"method":"GET","relative_url":"me"}, {"method":"GET", "relative_url":"me?fields=friends.limit(100).fields(music)"}]}, access_token=self.current_user["access_token"])
        #print me       

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def friendlist(self, res):
        #if else statement here to test whether friend size is larger than group or not
        groupsize = 30
        request_list = []
        for i in res["friends"]["data"]:
            batch_dict = {"method":"GET", "relative_url":str("%s?fields=movies,name,gender,sports,books,music,relationship_status,television,political,games,religion,education,interests,favorite_athletes,favorite_teams" % str(i["id"]))}
            request_list.append(batch_dict)
        requests =(request_list[i:i+groupsize] for i in xrange(0,len(request_list),groupsize))
        fdata = yield [tornado.gen.Task(self.facebook_request, "", post_args={"batch":f}, access_token=self.current_user["access_token"]) for f in requests]
        yield tornado.gen.Task(self.batched_req_gen, fdata)

    @tornado.gen.coroutine
    def batched_req_gen(self, data):
        #O(n^2) if we can make this O(n), it will be perfect
        for i in data:
            for j in i:
                if "body" in j:
                    d = ast.literal_eval(j["body"])
                    if d:
                        if 'gender' in d:
                            #heirarchy of keys is keywords ie; 'movie', 'sports', etc and then 'data'
                            yield tornado.gen.Task(self.asynch_data_handler, d, "movies","sports","books","music","television","political","games","religion","education","interests","favorite_athletes","favorite_teams")
                        else:
                            #no gender specified, no need to scrape (unless they chose an interested in)
                            continue
                    else:
                        print "Something went wrong, retry facebook request"
                    #right here, call to asynch function that scrapes data, be careful, this could be O(n*n!)


    #use: pass in args for data collection, ie; movie, sports, etc
    @tornado.gen.coroutine
    def asynch_data_handler(self, data, *args):
        yield [tornado.gen.Task(self.asynch_data_scraper, data=data, keyword=k) for k in args]        

    @tornado.gen.coroutine
    def asynch_data_scraper(self, data, keyword, callback=None):
        #put keyword logic here
        if keyword in data:
            #print data[keyword], data["id"], data["name"], data["relationship_status"]
            #redis saves here
            key = data[keyword]
            if isinstance(key, list):
                if "school" in key[0]:
                    yield tornado.gen.Task(redis.hset, key[0]["school"]["id"], "name", key[0]["school"]["name"])
                    yield tornado.gen.Task(redis.sadd, "%s:%s:%s" % (keyword, key[0]["school"]["id"], 
                        data["gender"]), data["id"])
            # self.set_db(keyword, data[keyword], data["id"], data["name"], data["gender"])
                else:
                    for k in key:
                        yield tornado.gen.Task(redis.hset, k["id"], "name", k["name"])
                        yield tornado.gen.Task(redis.sadd,"%s:%s:%s" % (keyword, k["id"], data["gender"]), data["id"])
            elif isinstance(key, dict):
                for d in key["data"]:
                    yield tornado.gen.Task(redis.hset, d["id"], "name", d["name"])
                    yield tornado.gen.Task(redis.sadd, "%s:%s:%s" % (keyword, d["id"], data["gender"]), data["id"])
        else:
            pass


    #deprecate this
    @tornado.gen.coroutine
    def set_db(self, keyword, data, id, name, gender):
        #stuff is not saving to redis for some reason
        #put data scraper here
        #this returns
        #category_id:like_id:gender
        pipe = redis.pipeline()
        if isinstance(data, list):
            print data[0], "list"
            if "school" in data[0]:
                pipe.hset(data[0]["id"], data[0]["name"])
                pipe.sadd("%s:%s:%s" % (keyword, data[0]["id"], gender), id)
                yield tornado.gen.Task(pipe.execute)
            else:
                pipe.hset(data[0]["id"], data[0]["name"])
                pipe.sadd("%s:%s:%s" % (keyword, data[0]["id"], gender), id)
                yield tornado.gen.Task(pipe.execute)
        elif isinstance(data, dict):
            for d in data["data"]:
                pipe.hset(d["id"], d["name"])
                pipe.sadd("%s:%s:%s" % (keyword, d["id"], gender), id)
        else:
            logging.info("strange data type")


    @tornado.gen.coroutine
    def create_person(self, data):
        pipe = redis.pipeline()
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


class PrivacyHandler(BaseHandler):
    def get(self):
        logging.info(self.request.headers)
        return self.render("privacy.html")


class TermsHandler(BaseHandler):
    def get(self):
        logging.info(self.request.headers)
        return self.render("terms.html")


class PartnerModule(tornado.web.UIModule):

    def render(self, partner, css="", interests=False):
        return self.render_string("modules/partner.html",
                                  partner=partner,
                                  css=css,
                                  interests=interests)


class ContenderModule(tornado.web.UIModule):

    def render(self, contenders):
        self.render_string("modules/contender.html", contenders=contenders)


def main():
    tornado.web.ErrorHandler = ExceptionHandler
    tornado.options.parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    logging.info("listening on :%s" % options.port)
    tornado.ioloop.IOLoop.instance().start()


if __name__ == "__main__":
    main()
