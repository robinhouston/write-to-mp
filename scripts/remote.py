#!/usr/bin/python
import code
import getpass
import os
import sys
import urllib2

# SDK paths
sys.path += [
  "/usr/local/google_appengine",
  "/usr/local/google_appengine/lib/yaml/lib",
  "/usr/local/google_appengine/lib/django",
  "/usr/local/google_appengine/lib/fancy_urllib",
  "/usr/local/google_appengine/lib/webob",
]

# Local application path
app_path = os.path.join(os.path.dirname(__file__), "..")
sys.path.append(app_path)


from google.appengine.ext.remote_api import remote_api_stub
from google.appengine.ext import db

import yaml
APP_ID = yaml.load(open(os.path.join(app_path, "app.yaml")))["application"]

def auth_func():
  global username, password
  return username, password

username, host, password = None, None, None
while len(sys.argv) > 1 and sys.argv[1].startswith("--"):
  switch = sys.argv[1]
  if switch == "--email":
    username = sys.argv[2]
    sys.argv[1:] = sys.argv[3:]
  elif switch == "--localport":
    host, username, password = "localhost:" + sys.argv[2], "remote.py", ""
    sys.argv[1:] = sys.argv[3:]

if len(sys.argv) > 2:
  host = sys.argv[2]
elif host is None:
  host = '%s.appspot.com' % APP_ID

def each(model_or_query, batch_size=50, in_batches=False, skip=0, keys_only=False):
  '''A generator that runs across all elements of a data store model,
  or all results of a simple filter query.
  '''

  if isinstance(model_or_query, type) and issubclass(model_or_query, db.Model):
    q = model_or_query.all(keys_only=keys_only)
  else:
    if model_or_query.is_keys_only() != keys_only:
      raise Exception("Parameter keys_only=%s, but supplied query has keys_only=%s",
        keys_only, model_or_query.is_keys_only())
    q = model_or_query
  
  while True:
    try:
      if skip <= batch_size:
        entities = q.fetch(batch_size, offset=skip)
        skip = 0
        skip_this_batch = False
      else:
        # Skip a complete batch
        entities = q.fetch(2, offset=batch_size-1)
        skip -= batch_size
        skip_this_batch = True
    except db.Timeout:
      import logging
      logging.warn("Data store timeout, trying again")
      continue
    except urllib2.URLError:
      import logging
      logging.warn("Caught URLError exception, retrying.")
      continue
    
    if skip_this_batch:
      pass
    elif in_batches:
      yield(entities)
    else:
      for entity in entities:
        yield(entity)
    
    if len(entities) < batch_size and not skip_this_batch:
      break
    
    q.with_cursor(q.cursor())

def each_batch(*args, **kwargs):
  '''A generator that runs across all elements of a data store model in batches.
  '''
  return each(*args, in_batches=True, **kwargs)

if username is None:
  username = raw_input('Username: ')
if password is None:
  password = getpass.getpass('Password: ')
remote_api_stub.ConfigureRemoteDatastore(APP_ID, '/remote_api', auth_func, host)

from mp import handlers as mps
os.environ["USER_EMAIL"] = "" # Otherwise the dev appserver can have assertion failures
code.interact('App Engine interactive console for %s on %s' % (APP_ID, host), None, locals())
