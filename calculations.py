import redis
import facebook
from celery import Celery


BROKER_URL = 'redis://localhost:6379/2'
celery = Celery("calculations", broker=BROKER_URL)
celery.conf.CELERY_RESULT_BACKEND = "redis://localhost:6379/0" 

r = redis.Redis(host="localhost", port=6379, db=0)


@celery.task
def 


#makes batched requests to facebook -> post req? 
def batch_req_gen():
    pass


if __name__ == "__main__":
    celery.start()