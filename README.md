matchmakr (name change pending)
=========
Dependencies (got to make requirements.txt)
redis
tornado-redis
tornado
logging


First start redis 
` $ redis-server `

Start wedding
` $ python wedding.py `


TODO:
- [ ] add both single and relationshipped people
- [ ] migrate to ec2
- [ ] setup nginx to handle static files
- [ ] asynch the fb requests in scrapehandler (40 sec avg is toooo slow)
