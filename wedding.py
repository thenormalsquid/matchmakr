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
#don't forget to change back to db1
redis = tornadoredis.Client(selected_db=2)
redis.connect()

pipe = redis.pipeline()

class Application(tornado.web.Application):

    def __init__(self):
        debug = (tornado.options.options.environment == "dev")
        handlers = [
            #/user, /matches  are for the api
            (r"/", IndexHandler),
            (r"/main", MainHandler),
            (r"/love", BatchHandler),
            (r"/user", UserHandler),
            (r"/mymatches", CalculatedHandler),
            (r"/matches", MatchApi),
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


class UserHandler(BaseHandler, tornado.auth.FacebookGraphMixin):
    """
    Returns a json representation of current user
    """

    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def get(self):
        user = yield tornado.gen.Task(redis.hgetall, "users:%s" % self.current_user["id"])
        self.write(tornado.escape.json_encode(user))


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

            # #use this once testing phase is complete
            # logging.debug("prompting user for gender attraction")                
            # user = yield tornado.gen.Task(redis.hgetall, "users:%s" % self.current_user["id"])
            # #show gender selection form always (like bang with friends)
            # self.write(user)

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
                    pipe.sadd("user_likes:%s" % (d["id"]), "%s:%s" % (item[0],like["id"]))
                    pipe.hmset("%s:%s" % (item[0], like["id"]), {"name": like["name"], "id": like["id"]})
        yield tornado.gen.Task(pipe.execute)


class CalculatedHandler(BaseHandler, tornado.auth.FacebookGraphMixin):
    #return json array api
    @tornado.web.asynchronous
    @tornado.web.authenticated
    @tornado.gen.coroutine
    def get(self):
        yield self.get_matches()

    @tornado.gen.coroutine
    def get_matches(self):
        pipe = redis.pipeline()
        matches = yield tornado.gen.Task(redis.zrevrange, "matches:%s" % (self.current_user["id"]), 0, -1, with_scores=False)
        match_list = []
        for match in matches:
            person = yield tornado.gen.Task(redis.hgetall, match)
            person["likes"] = ast.literal_eval(person["likes"])
            match_list.append(person)
        try:  
            #deprecate partner.html as we switch to angular for the ui
            self.render("partner.html", top_match=match_list[0], matches=match_list[1:])
            #first in match_list is the 
            #self.write(tornado.escape.json_encode(match_list))
        except IndexError:
            self.render("partner.html", top_match=None, matches=None)


class BatchHandler(BaseHandler, tornado.auth.FacebookGraphMixin):
    """
        This handler stores data, not retrieve
    """
    
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        calc_cache = yield tornado.gen.Task(redis.exists, "calculated:%s" % (self.current_user["id"]))
        if calc_cache:
            self.redirect("/mymatches")
        else:
            res = yield self.facebook_request("/me", self.create_person,
                                          access_token=self.current_user["access_token"], fields="friends.fields(id,name,interested_in,relationship_status,gender,birthday)")
            yield self.friendlist(res)

    
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
        pipe = redis.pipeline()
        for i in data:
            for j in i:
                if "body" in j:
                    d = ast.literal_eval(j["body"])
                    if d:
                        if 'gender' in d:
                            #heirarchy of keys is keywords ie; 'movie', 'sports', etc and then 'data'
                            yield tornado.gen.Task(self.asynch_data_handler, d, pipe, "movies","sports","books","music","television","political","games","religion","education","interests","favorite_athletes","favorite_teams")
                        else:
                            #no gender specified, no need to scrape (unless they chose an interested in)
                            continue
                    else:
                        print "Something went wrong, retry facebook request"
                    #right here, call to asynch function that scrapes data, be careful, this could be O(n*n!)
        yield tornado.gen.Task(pipe.execute) 
        yield tornado.gen.Task(self.make_matches)   
        yield tornado.gen.Task(redis.setex, "calculated:%s" % self.current_user["id"], 518400, "True")

    
    @tornado.gen.coroutine
    def asynch_data_handler(self, data, pipe, *args):
        yield [tornado.gen.Task(self.asynch_data_scraper, pipe=pipe, data=data, keyword=k) for k in args]        
    
    @tornado.gen.coroutine
    def asynch_data_scraper(self, pipe, data, keyword, callback=None):
        #put keyword logic here
        if keyword in data:
            #print data[keyword], data["id"], data["name"], data["relationship_status"]
            #redis saves here
            key = data[keyword]
            if isinstance(key, list):
                if "school" in key[0]:
                    pipe.sadd("%s:%s:%s" % (keyword, key[0]["school"]["id"], 
                        data["gender"]), data["id"])
                else:
                    for k in key:
                        pipe.sadd("%s:%s:%s" % (keyword, k["id"], data["gender"]), data["id"])
            elif isinstance(key, dict):
                for d in key["data"]:
                    pipe.sadd("%s:%s:%s" % (keyword, d["id"], data["gender"]), data["id"])
                    
        else:
            pass


    @tornado.gen.coroutine
    def create_person(self, data):
        pipe = redis.pipeline()
        d = data["friends"]["data"]
        for i in d:
            if "relationship_status" not in i:
                pipe.hmset("users:%s" % i["id"], i)
            else:
                pipe.hmset("users:%s" % i["id"], i)
        pipe.hset("users:%s" % self.current_user["id"], "f_check", "True")
        yield tornado.gen.Task(pipe.execute)


    @tornado.gen.coroutine
    def make_matches(self):
        pipe = redis.pipeline()
        categories = ["movies","sports","books","music","television","political","games","religion","education","interests","favorite_athletes","favorite_teams"]
        pipe.hget("users:%s" % self.current_user["id"], "attracted_to")
        pipe.smembers("user_likes:%s" % self.current_user["id"])
        attracted_to, user_likes = yield tornado.gen.Task(pipe.execute)
        match_list = []
        for like in user_likes:
            exists = yield tornado.gen.Task(redis.exists, "%s:%s" %(like, attracted_to))
            if exists:
                matches = yield tornado.gen.Task(redis.smembers, "%s:%s" % (like, attracted_to))
                #check to see if match exists so we don't have to recalc this everytime
                for match in matches:
                    match_exists = yield tornado.gen.Task(redis.exists, "match:%s:%s" % (match, self.current_user["id"]))
                    if match_exists:
                       continue
                    else:
                        pipe.sadd("match_likes:%s:%s" % (match, self.current_user["id"]), like)
                        match_list.append(match)
        yield tornado.gen.Task(pipe.execute)
        for match in match_list:
            like_dict = {cat: [] for cat in categories}
            person = yield tornado.gen.Task(redis.hgetall, "users:%s" % match)
            likes = yield tornado.gen.Task(redis.smembers, "match_likes:%s:%s" %(match, self.current_user["id"]))
            for like in likes:
                cat, lid = like.split(":")
                raw = yield tornado.gen.Task(redis.hgetall, like)
                like_dict[cat].append(raw)
            person["likes"] = like_dict
            print person
            pipe.hmset("match:%s:%s" % (match, self.current_user["id"]), person)
            pipe.zadd("matches:%s" % self.current_user["id"], match_list.count(match), "match:%s:%s" % (match, self.current_user["id"]))
        yield tornado.gen.Task(pipe.execute)

    #signals to angular that calculation has finished
    def on_finish(self):
        print "calc finished"

    #signals angular that calc has started
    def prepare(self):
        print "calc started"
        self.write({"calculation_finished": True})


class MatchApi(BaseHandler, tornado.auth.FacebookGraphMixin):
    @tornado.web.asynchronous
    @tornado.web.authenticated
    def get(self):
        pipe = redis.pipeline()
        matches = yield tornado.gen.Task(redis.zrevrange, "matches:%s" % (self.current_user["id"]), 0, -1, with_scores=False)
        match_list = []
        for match in matches:
            person = yield tornado.gen.Task(redis.hgetall, match)
            match_list.append(person)
        try:  
            #deprecate partner.html as we switch to angular for the ui
            #self.render("partner.html", top_match=match_list[0], matches=match_list)
            #first in match_list is the 
            self.write(tornado.escape.json_encode(match_list))
        except IndexError:
            self.write(None)

class PrivacyHandler(BaseHandler):
    def get(self):
        logging.info(self.request.headers)
        return self.render("privacy.html")


class TermsHandler(BaseHandler):
    def get(self):
        logging.info(self.request.headers)
        return self.render("terms.html")


class PartnerModule(tornado.web.UIModule):
    #may need to deprecate this module, if we're going the angular route
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
