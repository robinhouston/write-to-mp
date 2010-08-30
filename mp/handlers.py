import datetime
import logging
import os
import re
import sys
import urllib

from django.utils import simplejson as json
from google.appengine.api import mail
from google.appengine.api import urlfetch
from google.appengine.api.labs import taskqueue
from google.appengine.ext import db
from google.appengine.ext import webapp
import google.appengine.ext.webapp.util
from google.appengine.ext.webapp import template

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "pylib"))
import markdown

md = markdown.Markdown()


# Constants

TWFY_API_KEY = "REPLACE_THIS_WITH_YOUR_API_KEY"

# Data

class MPFormUser(db.Model):
  name = db.StringProperty()
  email = db.StringProperty()
  postcode = db.StringProperty()
  
  t_created = db.DateTimeProperty(required=True, auto_now_add=True)
  t_modified = db.DateTimeProperty(required=True, auto_now=True)

class MPLetter(db.Expando):
  # Parent entity should be the MP
  t_created = db.DateTimeProperty(required=True, auto_now_add=True)
  t_modified = db.DateTimeProperty(required=True, auto_now=True)
  
  body = db.TextProperty()

class MPGroup(db.Model):
  t_modified = db.DateTimeProperty(auto_now=True)
  name = db.StringProperty(required=True)
  blurb = db.TextProperty()

class MP(db.Model):
  t_modified = db.DateTimeProperty(auto_now=True)
  twfy_member_id = db.IntegerProperty(required=True)
  twfy_person_id = db.IntegerProperty(required=True)
  name = db.StringProperty(required=True)
  party = db.StringProperty()
  constituency = db.StringProperty(required=True)
  group = db.ReferenceProperty(MPGroup, required=True)
  positions = db.StringListProperty(default=[])
  
  def group_key(self):
    return self.__class__.group.get_value_for_datastore(self)

# Request handlers

class PageHandler(webapp.RequestHandler):
  def get(self):
    if self.request.get("change-postcode"):
      mp_json = None
    else:
      try:
        mp_json = self.get_mp_json()
      except urlfetch.DownloadError:
        self.redirect(self.request.url)
        return
    if mp_json:
      mp = json.loads(mp_json)
      if "error" in mp:
        template_path = "enter.html"
        advice, mysociety_serialized_variables = None, None
      else:
        template_path = "write.html"
        mysociety_serialized_variables = self.get_mysociety_serialized_variables(self.request.get("postcode"))
        
        logging.info("Getting blurb for MP with person_id %d", int(mp["person_id"]))
        mp_entities = MP.all().filter("twfy_person_id =", int(mp["person_id"])).fetch(1)
        if not mp_entities:
          logging.error("Could not find MP with person_id %s. Using default blurb.", mp["person_id"])
          group = MPGroup.get_by_key_name("Default")
          if not group:
            group = MPGroup(key_name="Default", name="Default")
            group.put()
        else:
          group = mp_entities[0].group
      
        blurb = group.blurb
        advice = md.convert(blurb) if blurb else ""
    else:
      template_path = "enter.html"
      mp, advice, mysociety_serialized_variables = None, None, None
    
    template_vars = {
      "mp_json": mp_json,
      "mp": mp,
      "mysociety_serialized_variables": mysociety_serialized_variables,
      "advice": advice,
      "not_your_mp_href": self.request.url + "&change-postcode=1",
      "change_postcode": bool(self.request.get("change-postcode")),
    }
    template_vars.update(self.request.params)
    self.response.out.write(webapp.template.render(template_path, template_vars))
  
  def get_mp_json(self):
    postcode = self.request.get("postcode")
    if not postcode:
      return None
    url = "http://www.theyworkforyou.com/api/getMP?"+ urllib.urlencode({
      "key": TWFY_API_KEY,
      "output": "js",
      "postcode": postcode
    })
    result = urlfetch.fetch(url, None, urlfetch.GET, deadline=10)
    if result.status_code != 200:
      logging.warn("MP lookup failed for postcode '%s'", postcode)
      return None
    return result.content.decode("latin-1").encode("utf-8")
  
  def get_mysociety_serialized_variables(self, postcode):
    url = "http://www.writetothem.com/?" + urllib.urlencode({
      "a": "westminstermp", "pc": postcode
    })
    
    # The urlfetch module does not correctly process this redirect
    result = urlfetch.fetch(url, follow_redirects=False, deadline=10)
    if result.status_code != 302:
      raise Exception("Unexpected code %s from %s" % (result.status_code, url))
    new_location = result.headers["location"]
    if not new_location.startswith("http://"):
      if not new_location.startswith("/"):
        new_location = "/" + new_location
      new_location = "http://www.writetothem.com" + new_location
    
    result = urlfetch.fetch(new_location, follow_redirects=False, deadline=10)
    if result.status_code != 200:
      raise Exception("Unexpected code %s from %s" % (result.status_code, new_location))
    mo = re.search(r'<input name="mysociety_serialized_variables" type="hidden" value="([^"]+)">', result.content)
    if not mo:
      raise Exception("Could not find mysociety_serialized_variables in %s" % (new_location))
    return mo.group(1)

class LetterSentHandler(webapp.RequestHandler):
  def post(self):
    p = {}
    for k, v in self.request.params.iteritems():
      p[str(k)] = unicode(v)
    logging.info(p)
    mp_person_id = p.pop("mp_person_id")
    logging.info("Getting MP with twfy_person_id=%s", mp_person_id)
    mp_key = MP.all(keys_only=True).filter("twfy_person_id =", int(mp_person_id)).fetch(1)[0]
    MPLetter(parent=mp_key, **p).put()
    
    # The 10:10 Lighter Later implementation sends an email message two weeks later
    # to anyone who has previewed a letter on WriteToThem, to ask whether they have
    # had a response from their MP and how the MP responded. To enable this feature
    # you must:
    #
    # 1. Uncomment the code immediately below.
    # 2. Uncomment the class TaskTwoWeeksLater and the reference to it in main().
    # 3. Put your sender email address in the marked place in TwoWeeksLater. This
    #    must be an authorised sender address by the app engine rules: the simplest
    #    way to ensure this for an arbitrary address is to make a corresponding Google
    #    account, and make that account an administrator of your application.
    # 4. Create plain text and HTML versions of the message you want to send, in
    #    files email/two-weeks-later.txt and email/two-weeks-later.html. These are
    #    templates, so can contain the placeholders {{ name }} and {{ email }} which
    #    are replaced, respectively, with the name and email address of the recipient.
    # 5. Add a task queue definition to queue.yaml, with queue name "write-to-mp".
    
    # two_weeks_time = datetime.date.today() + datetime.timedelta(days=14)
    # eta = datetime.datetime(two_weeks_time.year, two_weeks_time.month, two_weeks_time.day, 9, 30)
    # taskqueue.Queue("write-to-mp").add(taskqueue.Task(
    #   eta=eta, url="/mp/task/two-weeks-later",
    #   payload=urllib.urlencode({
    #     "email": self.request.get("writer_email"),
    #     "name": self.request.get("name"),
    #   }),
    # ))

class AdminHandler(webapp.RequestHandler):
  __error = None
  __group = None
  
  def get(self):
    mp_groups = MPGroup.all().order("__key__").fetch(1000)
    if len(mp_groups) < 1:
      mp_groups = [ MPGroup(key_name="Default", name="Default") ]
      db.put(mp_groups)
    js_mps_by_group, js_all_mps = self.js_mp_info(mp_groups)
    if not self.__group:
      if self.request.get("group"):
        self.__group = db.Key(self.request.get("group"))
      else:
        self.__group = db.Key.from_path("MPGroup", "Default")
    template_vars = {
      "group_to_select": self.__group,
      "js_blurb": self.js_blurb(mp_groups),
      "mp_groups": mp_groups,
      "js_groups": json.dumps(dict( (str(g.key()), g.name) for g in mp_groups)),
      "js_mps_by_group": js_mps_by_group,
      "js_all_mps": js_all_mps,
      "default_group": db.Key.from_path("MPGroup", "Default"),
      "error": self.__error,
    }
    self.response.out.write(webapp.template.render("admin.html", template_vars))
  
  def js_blurb(self, mp_groups):
    return json.dumps(dict(
      (str(mp_group.key()), mp_group.blurb) for mp_group in mp_groups
    ))
  
  def js_mp_info(self, mp_groups):
    mps_by_group = dict( (str(mp_group.key()), []) for mp_group in mp_groups )
    all_mps = {}
    
    for mp in MP.all():
      group_key = MP.group.get_value_for_datastore(mp)
      all_mps[str(mp.key())] = {
        "group": str(group_key) if group_key else None,
        "name": mp.name,
        "party": mp.party,
        "constituency": mp.constituency,
      }
      group_key = MP.group.get_value_for_datastore(mp)
      if group_key.name() == "Default" or str(group_key) not in mps_by_group:
        continue
      mps_by_group[str(group_key)].append(str(mp.key()))
    return json.dumps(mps_by_group), json.dumps(all_mps)
  
  def post(self):
    action = self.request.get("action").lower()
    if action.startswith("new"):
      self.__group = self.new_group(self.request.get("new-group-name"))
    elif action.startswith("save"):
      self.__group = self.save_group(self.request.get("group"), self.request.get("blurb"))
    elif action.startswith("delete"):
      self.delete_group(self.request.get("group"))
      self.__group = db.Key.from_path("MPGroup", "Default")
    
    return self.get()
  
  def new_group(self, name):
    if 0 < MPGroup.all().filter("name =", name).count(1):
      self.__error = "A group of that name already exists"
      return
    return db.run_in_transaction(self._new_group, name)
  def _new_group(self, name):
    g = MPGroup(name=name)
    g.put()
    return g.key()
  
  def save_group(self, key_str, blurb):
    logging.info("Setting blurb for key %s", key_str)
    return db.run_in_transaction(self._save_group, db.Key(key_str), blurb)
  def _save_group(self, key, blurb):
    mp_group = MPGroup.get(key)
    if not mp_group:
      self.__error = "MP group not found!"
      return
    mp_group.blurb = blurb
    mp_group.put()
    return mp_group.key()
  
  def delete_group(self, key_str):
    key = db.Key(key_str)
    if key.name() and key.name() == "Default":
      self.__error = "You can't delete the default group"
      return
    
    default_group = db.Key.from_path("MPGroup", "Default")
    for mp_key in MP.all(keys_only=True).filter("group =", key):
      db.run_in_transaction(self._set_group, mp_key, default_group)
    db.delete(key)
  
  def _set_group(self, mp_key, group_key):
    mp = MP.get(mp_key)
    mp.group = group_key
    mp.put()

class RestError(Exception):
  pass

class RestHandler(webapp.RequestHandler):
  def post(self, mp_key):
    try:
      response = self.add_to_group(db.Key(mp_key), db.Key(self.request.get("group")))
      response["ok"] = True
    except RestError, e:
      response = { "ok": False, "error": e.args[0] }
    
    self.response.headers["Content-type"] = "application/json"
    self.response.out.write(json.dumps(response))
  
  def add_to_group(self, mp_key, group_key):
    if not MPGroup.get(group_key):
      raise RestError("Group not found")

    return db.run_in_transaction(self._add_to_group, mp_key, group_key)
  
  def _add_to_group(self, mp_key, group_key):
    mp = MP.get(mp_key)
    if not mp:
      self.error(404)
      return
    previous_group = str(MP.group.get_value_for_datastore(mp))
    mp.group = group_key
    mp.put()
    return {"previous_group": previous_group}

class GroupRestHandler(webapp.RequestHandler):
  def post(self, group_key_str):
    try:
      response = self.set_group_name(db.Key(group_key_str), self.request.get("name"))
      response["ok"] = True
    except RestError, e:
      response = { "ok": False, "error": e.args[0] }
    
    self.response.headers["Content-type"] = "application/json"
    self.response.out.write(json.dumps(response))
  
  def set_group_name(self, group_key, name):
    # Yeah, this is a race condition - but the worst that can happen is
    # you end up with two groups of the same name and have to rename one.
    if 0 < MPGroup.all().filter("name =", name).count(1):
      raise RestError("There is already a group of that name")
    db.run_in_transaction(self._set_group_name, group_key, name)
    return {}
  
  def _set_group_name(self, group_key, name):
    group = MPGroup.get(group_key)
    group.name = name
    group.put()

class AdminListHandler(webapp.RequestHandler):
  def get(self):
    self.response.out.write(webapp.template.render("admin-list.html", {
      "mps": MP.all().order("name").fetch(1000),
      "groups": MPGroup.all().order("__key__").fetch(1000),
    }))

class CronNewMPs(webapp.RequestHandler):
  def get(self):
    '''Find any MPs we don't have in the database, and add them.
    '''
    db.run_in_transaction(self._ensure_default_mp_group)
    
    url = "http://www.theyworkforyou.com/api/getMPs?"+ urllib.urlencode({
      "key": TWFY_API_KEY,
    })
    result = urlfetch.fetch(url, None, urlfetch.GET)
    if result.status_code != 200:
      raise Exception("Failed to fetch MP details (status %s)" % (result.status_code,))
  
    assert result.headers["content-type"] == "text/javascript; charset=iso-8859-1"
    mps = json.loads(result.content.decode("latin-1").encode("utf-8"))
    
    if "error" in mps:
      logging.error("Error fetching new MPs: %s", mps["error"])
      self.response.headers["Content-type"] = "text/plain; charset=utf-8"
      self.response.out.write("Error: " + mps["error"])
      return
    
    tasks = []

    while mps:
      this_batch, mps = mps[:200], mps[200:]
      key_names = [ "twfy_person_id=%d" % int(mp["person_id"]) for mp in this_batch ]
      entities = MP.get_by_key_name(key_names)
      for i in range(len(key_names)):
        if not entities[i]:
          tasks.append(taskqueue.Task(
            url = "/mp/cron/task/update_mp/%d" % (int(this_batch[i]["person_id"]),),
            payload = None,
          ))
    
    queue = taskqueue.Queue("mp")
    while tasks:
      this_batch, tasks = tasks[:100], tasks[100:]
      queue.add(this_batch)
    
    self.response.headers["Content-type"] = "text/plain; charset=utf-8"
    self.response.out.write("Fetching new MPs in the background")
  
  def _ensure_default_mp_group(self):
    if not MPGroup.get_by_key_name("Default"):
      MPGroup(key_name="Default", name="Default").put()

class CronUpdateMPs(webapp.RequestHandler):
  def get(self):
    '''Update all the MPs in the database from theyworkforyou, in case any have left or changed position.
    '''
    queue = taskqueue.Queue("mp")
    q = MP.all()
    while True:
      mps = q.fetch(100)
      
      queue.add([
        taskqueue.Task(
          url = "/mp/cron/task/update_mp/%d" % (mp.twfy_person_id,),
          payload = None,
        )
        for mp in mps
      ])
      
      if len(mps) < 100:
        break
      
      q.with_cursor(q.cursor())

class TaskUpdateMP(webapp.RequestHandler):
  def post(self, twfy_person_id_str):
    '''Update the details of the MP with the person_id specified in the URL.
    '''
    twfy_person_id = int(twfy_person_id_str)
    
    url = "http://www.theyworkforyou.com/api/getMP?"+ urllib.urlencode({
      "key": TWFY_API_KEY,
      "output": "js",
      "id": str(twfy_person_id),
    })
    result = urlfetch.fetch(url, None, urlfetch.GET)
    if result.status_code != 200:
      raise Exception("MP lookup failed for person_id %d", twfy_person_id)

    mp_info = json.loads(result.content.decode("latin-1").encode("utf-8"))[0]
    mp_key = db.Key.from_path("MP", "twfy_person_id=%d" % (twfy_person_id,))
    
    if mp_info["left_reason"] != "still_in_office":
      logging.info("MP %s (%s) has left office: %s", mp_info["name"], mp_info["constituency"], mp_info["left_reason"])
      db.delete(mp_key)
      
    else:
      office = mp_info.get("office")
      if office:
        positions = [
          position["position"] + (", " + position["dept"] if position.get("dept") else "")
          for position in office
        ]
      else:
        positions = []
      
      logging.info("mp_info = %s", mp_info)
      db.run_in_transaction(self._update_mp, mp_key,
        default_mp_group = MPGroup.get_by_key_name("Default"),
        twfy_member_id = int(mp_info["member_id"]),
        twfy_person_id = int(mp_info["person_id"]),
        name = mp_info["full_name"],
        party = mp_info["party"],
        constituency = mp_info["constituency"],
        positions = positions,
      )
  
  def _update_mp(self, key, default_mp_group, **kwargs):
    entity = db.get(key)
    if entity:
      for name, value in kwargs.items():
        setattr(entity, name, value)
      entity.put()
    else:
      MP(key_name=key.name(), group=default_mp_group, **kwargs).put()
  
  def get(self, twfy_person_id_str):
    self.response.out.write("<form method='POST'><input type='submit' value='Update'></form>")

# class TaskTwoWeeksLater(webapp.RequestHandler):
#   def post(self):
#     email, name = self.request.get("email"), self.request.get("name")
#     
#     mail.send_mail(
#       subject = "Did you hear back from your MP?",
#       sender = "", # <- PUT YOUR SENDER ADDRESS HERE
#       reply_to = "mpresponse@lighterlater.org",
#       to = email,
#       body = template.render("email/two-weeks-later.txt",  {"name": name, "email": email}),
#       html = template.render("email/two-weeks-later.html", {"name": name, "email": email}),
#     )
#     logging.info("Sent 'two weeks later' email to %s <%s>", name, email)

class AdminSentHandler(webapp.RequestHandler):
  def get(self):
    self.response.out.write(webapp.template.render("admin-sent.html", {
      "letters": MPLetter.all().order("t_created"),
    }))


def main():
  handlers = [
    (r'/mp/write', PageHandler),
    (r'/mp/letter-sent', LetterSentHandler),
    
    (r'/mp/admin', AdminHandler),
    (r'/mp/admin/list', AdminListHandler),
    (r'/mp/key/(.+)', RestHandler),
    (r'/mp/group/(.+)', GroupRestHandler),
    (r'/mp/admin/sent', AdminSentHandler),
    
    (r'/mp/cron/new_mps', CronNewMPs),
    (r'/mp/cron/update_mps', CronUpdateMPs),
    (r'/mp/cron/task/update_mp/(\d+)', TaskUpdateMP),
    
#    (r'/mp/task/two-weeks-later', TaskTwoWeeksLater),
  ]
  webapp.util.run_wsgi_app(
    webapp.WSGIApplication(handlers, debug=False))

if __name__ == '__main__':
  main()
