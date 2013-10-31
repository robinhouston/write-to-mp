# -*- encoding: utf-8 -*-

import json
import logging
import os
import re
import sys
import urllib

import jinja2
import webapp2

from google.appengine.api import urlfetch
from google.appengine.ext import db

APP_DIR = os.path.dirname(__file__)

# Configure Jinja2
jin = jinja2.Environment(
  loader=jinja2.FileSystemLoader(APP_DIR),
  extensions=['jinja2.ext.autoescape'],
  autoescape = lambda t: (t is None or re.match(r".*\.(html|htm|xml)$", t) is not None),
)
jin.filters["linebreaksbr"] = lambda s: re.sub(r"\r?\n", jinja2.Markup("<br>"), jinja2.Markup.escape(s))

# Load and configure Markdown
sys.path.append(os.path.join(APP_DIR, os.path.pardir, "pylib"))
import markdown

md = markdown.Markdown()


# Settings

class Settings(db.Model):
  twfy_api_key = db.StringProperty(default="UNSET")
  representative_type = db.StringProperty(default="MP", choices=["MP", "MSP"])
  favicon_url = db.StringProperty(default="")
  intro_markdown = db.TextProperty(default="")
  store_what = db.StringProperty(default="nothing", choices=["nothing", "name_email_and_postcode", "letter"])
  opt_in_checkbox_text = db.StringProperty(default="")

def settings():
  return Settings.get_by_key_name("settings") or Settings(key_name="settings")

# Data

class MPFormUser(db.Model):
  name = db.StringProperty()
  email = db.StringProperty()
  postcode = db.StringProperty()
  opted_in = db.BooleanProperty(default=False)
  
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

# Utility functions

def json_dumps(data):
    return jinja2.Markup(json.dumps(data))

def md_convert(markdown_text):
    return jinja2.Markup(md.convert(markdown_text))

# Request handlers

class PageHandler(webapp2.RequestHandler):
  def get(self):
    if self.request.get("change-postcode"):
      mp_json = None
    else:
      try:
        mp_json = self.get_mp_json()
      except urlfetch.DownloadError:
        self.redirect(self.request.url)
        return
    
    representative_type = settings().representative_type
    mp, advice, mysociety_serialized_variables = None, None, None
    template_path = "enter.html"
    
    if mp_json:
      mp = json.loads(mp_json)
      if isinstance(mp, list):
        # For MSPs we get a list of representatives. Take the first.
        mp = mp[0]
      if mp == {}:
        mp["error"] = "Your constituency does not currently have an " + representative_type
      elif "error" not in mp:
        template_path = "write.html"
        mysociety_serialized_variables = self.get_mysociety_serialized_variables(self.request.get("postcode"))
        
        logging.info("Getting blurb for %s with person_id %d", representative_type, int(mp["person_id"]))
        mp_entities = MP.all().filter("twfy_person_id =", int(mp["person_id"])).fetch(1)
        if not mp_entities:
          logging.error("Could not find %s with person_id %s. Using default blurb.", representative_type, mp["person_id"])
          group = MPGroup.get_by_key_name("Default")
          if not group:
            group = MPGroup(key_name="Default", name="Default")
            group.put()
        else:
          group = mp_entities[0].group
      
        blurb = group.blurb
        advice = md_convert(blurb) if blurb else ""
    
    intro_text_md = settings().intro_markdown
    intro_text_html = md_convert(intro_text_md) if intro_text_md else None
    
    template_vars = {
      "mp_json": mp_json,
      "mp": mp,
      "mysociety_serialized_variables": mysociety_serialized_variables,
      "advice": advice,
      "not_your_mp_href": self.request.url + "&change-postcode=1",
      "change_postcode": bool(self.request.get("change-postcode")),
      "intro_text": intro_text_html,
      "representative_type": representative_type,
      "store_what": settings().store_what,
      "opt_in_checkbox_text": settings().opt_in_checkbox_text,
    }
    template_vars.update(self.request.params)
    self.response.out.write(jin.get_template(template_path).render(template_vars))
  
  def get_mp_json(self):
    postcode = self.request.get("postcode")
    if not postcode:
      return None
    representative_type = settings().representative_type
    url = "http://www.theyworkforyou.com/api/get"+representative_type+"?"+ urllib.urlencode({
      "key": settings().twfy_api_key,
      "output": "js",
      "postcode": postcode
    })
    result = urlfetch.fetch(url, None, urlfetch.GET, deadline=10)
    if result.status_code != 200:
      logging.warn("MP lookup failed for postcode '%s'", postcode)
      return None
    return result.content.decode("latin-1").encode("utf-8")
  
  def get_mysociety_serialized_variables(self, postcode):
    representative_type = settings().representative_type
    wtt_representative_type = {"MP": "westminstermp", "MSP": "regionalmp"}[representative_type]
    url = "https://www.writetothem.com/?" + urllib.urlencode({
      "a": wtt_representative_type, "pc": postcode
    })
    
    # The urlfetch module does not correctly process this redirect
    result = urlfetch.fetch(url, follow_redirects=False, deadline=10)
    if result.status_code != 302:
      raise Exception("Unexpected code %s from %s" % (result.status_code, url))
    new_location = result.headers["location"]
    if not new_location.startswith("http://"):
      if not new_location.startswith("/"):
        new_location = "/" + new_location
      new_location = "https://www.writetothem.com" + new_location
    
    result = urlfetch.fetch(new_location, follow_redirects=False, deadline=10)
    if result.status_code != 200:
      raise Exception("Unexpected code %s from %s" % (result.status_code, new_location))
    
    # for MSPs, WriteToThem will return a list of regional MSPs as well as the actual
    # constituency MSP for the postcode. Follow the first /write link, which is the
    # user’s constituency MSP.
    if representative_type == "MSP":
      mo = re.search(r'<a href="(/write\?[^"]+)">', result.content)
      if not mo:
        raise Exception("Could not find <a href=\"/write?...\"> in %s" % (new_location,))
      new_location = "https://www.writetothem.com" + mo.group(1)
      result = urlfetch.fetch(new_location, follow_redirects=False, deadline=10)
      if result.status_code != 200:
        raise Exception("Unexpected code %s from %s" % (result.status_code, new_location))
    
    mo = re.search(r'<input name="mysociety_serialized_variables" type="hidden" value="([^"]+)">', result.content)
    if not mo:
      raise Exception("Could not find mysociety_serialized_variables in %s" % (new_location))
    return mo.group(1)

class LetterSentHandler(webapp2.RequestHandler):
  def post(self):
    p = {}
    for k, v in self.request.params.iteritems():
      p[str(k)] = unicode(v)
    logging.info(p)
    
    store_what = settings().store_what
    if store_what == "name_email_and_postcode":
      MPFormUser(
        name=p["name"], email=p["email"], postcode=p["postcode"],
        opted_in=bool(p["opted_in"])
      ).put()
    
    elif store_what == "letter":
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
    #   params={
    #     "email": self.request.get("writer_email"),
    #     "name": self.request.get("name"),
    #   },
    # ))

class AdminHandler(webapp2.RequestHandler):
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
      "js_groups": json_dumps(dict( (str(g.key()), g.name) for g in mp_groups)),
      "js_mps_by_group": js_mps_by_group,
      "js_all_mps": js_all_mps,
      "default_group": db.Key.from_path("MPGroup", "Default"),
      "error": self.__error,
      "settings": settings(),
    }
    self.response.out.write(jin.get_template("admin.html").render(template_vars))
  
  def js_blurb(self, mp_groups):
    return json_dumps(dict(
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
    return json_dumps(mps_by_group), json_dumps(all_mps)
  
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

class RestHandler(webapp2.RequestHandler):
  def post(self, mp_key):
    try:
      response = self.add_to_group(db.Key(mp_key), db.Key(self.request.get("group")))
      response["ok"] = True
    except RestError, e:
      response = { "ok": False, "error": e.args[0] }
    
    self.response.headers["Content-type"] = "application/json"
    self.response.out.write(json_dumps(response))
  
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

class GroupRestHandler(webapp2.RequestHandler):
  def post(self, group_key_str):
    try:
      response = self.set_group_name(db.Key(group_key_str), self.request.get("name"))
      response["ok"] = True
    except RestError, e:
      response = { "ok": False, "error": e.args[0] }
    
    self.response.headers["Content-type"] = "application/json"
    self.response.out.write(json_dumps(response))
  
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

class SettingsRestHandler(webapp2.RequestHandler):
  def post(self):
    s = settings()
    for setting_name in (
      "twfy_api_key", "representative_type", "intro_markdown",
      "favicon_url", "store_what", "opt_in_checkbox_text"
    ):
      if setting_name in self.request.params:
        setattr(s, setting_name, self.request.get(setting_name))
    s.put()

class AdminListHandler(webapp2.RequestHandler):
  def get(self):
    self.response.out.write(jin.get_template("admin-list.html").render({
      "mps": MP.all().order("name").fetch(1000),
      "groups": MPGroup.all().order("__key__").fetch(1000),
      "settings": settings(),
    }))

class AdminSettingsHandler(webapp2.RequestHandler):
  def get(self):
    self.response.out.write(jin.get_template("admin-settings.html").render({
      "settings": settings(),
    }))


class CronUpdateMPs(webapp2.RequestHandler):
  def get(self):
    '''Update all the MPs in the database from theyworkforyou, in case any have left or changed position.
    '''
    representative_type = settings().representative_type
    self.response.headers["Content-type"] = "text/plain; charset=utf-8"
    print >>self.response.out, "Updating list of MPs"
    print >>self.response.out, "--------------------"
    print >>self.response.out
    
    def _ensure_default_mp_group():
      if not MPGroup.get_by_key_name("Default"):
        MPGroup(key_name="Default", name="Default").put()
    db.run_in_transaction(_ensure_default_mp_group)
    
    print >>self.response.out, "Fetching the list of "+representative_type+"s from TheyWorkForYou..."
    url = "http://www.theyworkforyou.com/api/get"+representative_type+"s?"+ urllib.urlencode({
      "key": settings().twfy_api_key,
      "output": "js"
    })
    result = urlfetch.fetch(url, None, urlfetch.GET, deadline=60)
    if result.status_code != 200:
      raise Exception("Failed to fetch list of "+representative_type+"s from TheyWorkForYou")
    twfy_mps = json.loads(result.content.decode("latin-1").encode("utf-8"))
    
    mps_by_twfy_person_id = {}
    for twfy_mp in twfy_mps:
      mps_by_twfy_person_id[int(twfy_mp["person_id"])] = twfy_mp
    print >>self.response.out
    
    print >>self.response.out, "Checking existing "+representative_type+"s to see if anything has changed..."
    print >>self.response.out
    for mp in MP.all():
      print >>self.response.out, "Checking %s (%s)..." % (mp.name, mp.constituency)
      if mp.twfy_person_id not in mps_by_twfy_person_id:
        print >>self.response.out, u"\tNOT IN TWFY LIST – assuming they have left office"
        logging.info("%s %s (%s) has left office", representative_type, mp.name, mp.constituency)
        db.delete(mp.key())
        continue
      
      twfy_mp = mps_by_twfy_person_id.pop(mp.twfy_person_id)
      db.run_in_transaction(self._update_mp, mp.key(), twfy_mp)
    print >>self.response.out
    
    # New M(S)Ps
    print >>self.response.out, "Adding new "+representative_type+"s..."
    default_mp_group = MPGroup.get_by_key_name("Default")
    for twfy_mp in mps_by_twfy_person_id.values():
      print >>self.response.out, "New "+representative_type+" %s (%s)" % (twfy_mp["name"], twfy_mp["constituency"])
      logging.info("New %s %s (%s)", representative_type, twfy_mp["name"], twfy_mp["constituency"])
      db.run_in_transaction(self._new_mp, twfy_mp, default_mp_group)
    print >>self.response.out
    
    print >>self.response.out, "All done!"
  
  def _update_mp(self, key, twfy_mp):
    mp = db.get(key)
    changed = False
    if mp.name != twfy_mp["name"]:
      changed = True
      print >>self.response.out, "\tName changed from '%s' to '%s'" % (mp.name, twfy_mp["name"])
      mp.name = twfy_mp["name"]
    
    if mp.party != twfy_mp["party"]:
      changed = True
      print >>self.response.out, "\tParty changed from '%s' to '%s'" % (mp.party, twfy_mp["party"])
      mp.party = twfy_mp["party"]
    
    if mp.constituency != twfy_mp["constituency"]:
      changed = True
      print >>self.response.out, "\tConstituency changed from '%s' to '%s'" % (mp.constituency, twfy_mp["constituency"])
      mp.constituency = twfy_mp["constituency"]
    
    if mp.twfy_member_id != int(twfy_mp["member_id"]):
      changed = True
      print >>self.response.out, "\tMember ID changed from %d to %d" % (mp.twfy_member_id, int(twfy_mp["member_id"]))
      mp.twfy_member_id = int(twfy_mp["member_id"])
    
    positions = self._positions(twfy_mp)
    if positions != mp.positions:
      changed = True
      print >>self.response.out, "\tPositions changed from '%r' to '%r'" % (mp.positions, positions)
      mp.positions = positions
    
    if changed:
      mp.put()
  
  def _new_mp(self, twfy_mp, default_mp_group):
    MP(
      key_name="twfy_person_id=" + twfy_mp["person_id"],
      group=default_mp_group,
      twfy_member_id = int(twfy_mp["member_id"]),
      twfy_person_id = int(twfy_mp["person_id"]),
      name = twfy_mp["name"],
      party = twfy_mp["party"],
      constituency = twfy_mp["constituency"],
      positions = self._positions(twfy_mp),
    ).put()
  
  def _positions(self, twfy_mp):
    office = twfy_mp.get("office")
    if office:
      return [
        position["position"] + (", " + position["dept"] if position.get("dept") else "")
        for position in office
      ]
    return []

# class TaskTwoWeeksLater(webapp2.RequestHandler):
#   def post(self):
#     email, name = self.request.get("email"), self.request.get("name")
#     
#     mail.send_mail(
#       subject = "Did you hear back from your MP?",
#       sender = "", # <- PUT YOUR SENDER ADDRESS HERE
#       reply_to = "mpresponse@lighterlater.org",
#       to = email,
#       body = jin.get_template("email/two-weeks-later.txt").render({"name": name, "email": email}),
#       html = jin.get_template("email/two-weeks-later.html").render({"name": name, "email": email}),
#     )
#     logging.info("Sent 'two weeks later' email to %s <%s>", name, email)

class AdminSentHandler(webapp2.RequestHandler):
  def get(self):
    self.response.out.write(jin.get_template("admin-sent.html").render({
      "users": MPFormUser.all().order("t_created"),
      "letters": MPLetter.all().order("t_created"),
      "settings": settings(),
    }))

class FaviconHandler(webapp2.RequestHandler):
  def get(self):
    url = str(settings().favicon_url)
    if url:
      self.redirect(url)
    else:
      self.error(404)


app = webapp2.WSGIApplication([
  (r'/mp/write', PageHandler),
  (r'/mp/letter-sent', LetterSentHandler),
  
  (r'/mp/admin', AdminHandler),
  (r'/mp/admin/list', AdminListHandler),
  (r'/mp/admin/settings', AdminSettingsHandler),
  (r'/mp/key/(.+)', RestHandler),
  (r'/mp/group/(.+)', GroupRestHandler),
  (r'/mp/settings', SettingsRestHandler),
  (r'/mp/admin/sent', AdminSentHandler),
  
  (r'/mp/cron/update_mps', CronUpdateMPs),
  
  (r'/favicon\.ico', FaviconHandler),
  
#    (r'/mp/task/two-weeks-later', TaskTwoWeeksLater),
])
