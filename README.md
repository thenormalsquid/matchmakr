matchmakr (name change pending)
=========
Dependencies (got to make requirements.txt)
* redis
* tornado-redis
* tornado
* logging


First start redis 
` $ redis-server `

Start wedding
` $ python wedding.py `

Demo running at http://radicalcakes.udderweb.com:1935

Homewrecker mode

##Thien
TODO:
- [X] add both single and relationshipped people
- [X] Asynch scrape and calculations 
		-  match each call back in a callback, wait pair
		-  once loading completed, redirect to results page
- [X] TOS
- [X] Privacy Policy
- [ ] migrate to ec2
- [ ] setup nginx to handle static files


##Luqmaan
TODO:
Pages that need styling
- [] /main
- [] /yourmatches
- [] /privacy
- [] /terms
- [] /cookies
