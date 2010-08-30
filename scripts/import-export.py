# This is the export/import code used to create the local test data set
# You can't run it as a script: you have to copy/paste sections of it
# into the remote console provided by scripts/remote.py

# Run this when connected to a remote application that has a fully-populated
# list of MPs. It will create the file data/mps.json with their details.
json.dump([
  {
    "twfy_member_id": getattr(mp, "twfy_member_id"),
    "twfy_person_id": getattr(mp, "twfy_person_id"),
    "name": getattr(mp, "name"),
    "party": getattr(mp, "party"),
    "constituency": getattr(mp, "constituency"),
    "positions": getattr(mp, "positions"),
  }
  for mp in mps.MP.all()
], open("data/mps.json", "w"))


# Run this when connected to a local server, to populate it from data/mps.json
g = mps.MPGroup(key_name="Default", name="Default")
g.put()
for mp in json.load(open("data/mps.json")):
  # json.load creates unicode keys. We have to convert them to str
  # before they can be used as named arguments.
  mp_strs = dict((str(k), v) for k,v in mp.items())
  mps.MP(group=g.key(), **mp_strs).put()
