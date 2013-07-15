import random
import datetime
import redis

r = redis.Redis(host='localhost', port=6379, db=2)
pipe = r.pipeline()
#my id: 742308411

class Sender(object):

    def __init__(self, name, uid):
        self.name = name
        self.uid = str(uid)

    def create_msg(self, msg, rec_name="Thien-Bach Huynh", rec_id="742308411"):
        key = "%s:%s" %(rec_id, self.uid)
        pipe.sadd("%s:inbox" %  rec_id, key)
        msg_hash = {"from_name": self.name, "to_name":rec_name, "key":str(key), "from":self.uid, "to":rec_id,
            "msg": msg, "timestamp": str(datetime.datetime.now())}
        pipe.rpush(key, msg_hash)



if __name__ == "__main__":
    users = {"Courtney P": 54321, "Kathy P": 12345,  "Lindsay M": 987654, "Girly Girl": 109876}
    message_list = ["hi", "fuckyou", "poop", "wtf", "mofo", "god", "hellooo", "shit"]
    for (k,v) in users.iteritems():
        sender = Sender(k,v)
        msg = message_list[random.randrange(len(message_list))]
        sender.create_msg(msg)
    pipe.execute()