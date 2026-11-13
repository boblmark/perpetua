import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

ROW_KEY = "f937a5d49ee04a34bc2f8e6ef3959d73"
NEW_TITLE = "\U0001F35A Karen Lifted the Rice Cooker Lid \u2014 AI Steamed Her Glasses \U0001F602"

items = queue_db.pipeline_load()
target = None
for it in items:
    if it.get("_row_key") == ROW_KEY:
        target = it
        break
assert target is not None, "row not found"
assert target.get("topic") == "smart rice cooker", target.get("topic")
old_title = target["title"]
old_desc = target.get("description", "")
lines = old_desc.split("\n")
assert lines[0] == old_title, "desc first line != title: %r" % lines[0][:80]
lines[0] = NEW_TITLE
target["title"] = NEW_TITLE
target["description"] = "\n".join(lines)
target["status"] = "ready_to_upload"
target.pop("upload_failed_at", None)
target.pop("upload_failed_retries", None)
target["title_fixed_by"] = "dash_user_approved_20261113"
queue_db.pipeline_save(items)
print("OK old_title=%r" % old_title)
print("OK new_title=%r" % NEW_TITLE)

items2 = queue_db.pipeline_load()
t2 = [i for i in items2 if i.get("_row_key") == ROW_KEY][0]
print("VERIFY title=%r status=%r" % (t2["title"], t2["status"]))
print("VERIFY desc_head=%r" % t2["description"].split("\n")[0])
assert t2["title"] == NEW_TITLE and t2["status"] == "ready_to_upload"
print("VERIFIED")
