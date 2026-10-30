"""One-off: add 22 filtered Ask Studio device-pool topics as status=selected (user approved 2026-10-30 15:57).
Filtered from 25 Ask Studio ideas: bottle-return (vending variant) and subway fare gate (turnstile variant) removed;
tabletop ordering tablet held as borderline, NOT included. Slot left empty = future supply, not tonight 23:30.
Aborts on any dedup hit against existing topics/titles or within the batch."""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db
from datetime import datetime, timezone

ITEMS = [
    ("key_duplication_kiosk", "🔑Karen Copies A Master Key — The Kiosk Grinds It To Dust😂",
     "Karen demands a self-service key kiosk duplicate an unauthorized master key; the machine grinds it to metallic dust and dumps it into her purse."),
    ("crosswalk_button", "🚦Karen Smashes The Crosswalk Button — Locked On Don't Walk😂",
     "Karen mashes a pedestrian crosswalk button screaming at traffic; the speaker blares a countdown and locks the signal on Don't Walk for 30 minutes."),
    ("bowling_ball_return", "🎳Karen Shoves Her Foot In The Ball Return — Shoe Waxed Shut😂",
     "Karen shoves her foot into a bowling ball return to free a stuck ball; the sensor clamps a buffer pad over her designer shoe and waxes it shut."),
    ("museum_audio_guide", "🎧Karen Hijacks The Museum Audio Guide — Blasted With Harpsichord😂",
     "Karen demands a museum audio guide play pop music instead of art history; the lanyard tightens and blasts classical harpsichord at max volume."),
    ("restroom_hand_dryer", "🍕Karen Heats Pizza In The Hand Dryer — Slice Hits The Wall😂",
     "Karen holds damp takeout pizza under an automatic restroom hand dryer; the jet shifts to hurricane mode and blasts the slice across the wall."),
    ("gym_locker", "🔒Karen Refuses The Locker Fee — Her Purse Sealed Till Morning😂",
     "Karen refuses to pay a gym locker fee and kicks the door; the digital padlock snaps shut, sealing her purse inside until morning staff arrive."),
    ("ski_lift_bar", "🎿Karen Refuses The Ski-Lift Bar — Hydraulics Lock Her In😂",
     "Karen refuses to lower a ski-lift safety bar and yells at the camera; the bar snaps down with hydraulic force, locking her into her seat."),
    ("soft_drink_fountain", "🥤Karen Demands Free Refills — 10 Pounds Of Ice On Her Lap😂",
     "Karen shoves a bucket into a touchless soft-drink fountain ice chute demanding free refills; the machine dumps 10 pounds of crushed ice on her lap."),
    ("tan_booth", "🟢Karen Demands 4-Hour Ultra Tan — Green Mist To The Face😂",
     "Karen demands a 4-hour ultra-dark tan booth setting without safety goggles; the nozzles fire fluorescent green UV mist straight across her face."),
    ("fitting_room_mirror", "🪞Karen Demands Size Zero Override — Mirror Roasts Her On PA😂",
     "Karen demands a size zero barcode override at a smart fitting room mirror; the mirror fires a spotlight and announces 'Item does not fit' over the store PA."),
    ("park_water_fountain", "🐶Karen Bathes Her Dog In The Park Fountain — Fire-Hose Pressure😂",
     "Karen bathes her purse dog under a public park water fountain spout; the sensor spikes pressure into a fire-hose stream that drenches her."),
    ("coinstar_machine", "🪨Karen Feeds Gravel To Coinstar — Rocks Fired Back😂",
     "Karen dumps greasy gravel and rusty washers into a Coinstar tray demanding cash; the sorting blade ejects every dirty rock back into her handbag."),
    ("golf_ball_dispenser", "⛳Karen Steals Range Balls — Machine Fires 10 Into Her Trunk😂",
     "Karen steals extra buckets from a golf driving range ball dispenser; the floor feeder fires ten golf balls straight into her open trunk."),
    ("smart_mannequin", "🧥Karen Strips The Mannequin — Magnetic Grip Locks Her Wrist😂",
     "Karen tries to strip a designer coat off a department store smart mannequin; its magnetic grip clamps her wrist and triggers a shoplifting alarm."),
    ("lottery_kiosk", "🎰Karen Pounds The Lottery Kiosk — 100 Loser Tickets To The Face😂",
     "Karen pounds a self-service lottery kiosk touchscreen demanding a winning scratcher; the machine ejects 100 blank loser receipts into her face."),
    ("toll_barrier", "🚧Karen Tailgates The Toll Gate — Bumper Locked, Strobe Flashing😂",
     "Karen tailgates through a toll plaza without an electronic pass; the barrier arm drops, locking her bumper while a strobe camera flashes relentlessly."),
    ("nursery_mist_sprayer", "🌱Karen Steals Plant Cuttings — Fertilizer Drench From Above😂",
     "Karen snips plant cuttings into her bag at a nursery; the overhead mist bar switches to a high-pressure fertilizer drench directly above her."),
    ("ice_bag_dispenser", "🧊Karen Grabs Double Ice Bags — Chute Freezes Her Purse Strap😂",
     "Karen reaches inside a self-service ice bag dispenser chute to grab double bags; the internal gate closes and freezes her purse strap in place."),
    ("hotel_keycard_kiosk", "🏨Karen Demands A Penthouse — Gets The Linen Closet😂",
     "Karen berates a hotel check-in kiosk demanding a free penthouse upgrade; the dispenser issues a key marked 'Basement Linen Closet.'"),
    ("pool_cover_roller", "🌯Karen Jumps The Closed Pool — Rolled Up Like A Burrito😂",
     "Karen jumps onto a pool deck past closing hours; the motorized vinyl pool cover rolls out beneath her feet, rolling her up like a burrito."),
    ("arcade_ticket_eater", "🎟️Karen Feeds Fake Tickets — Confetti Spit Back In Her Mouth😂",
     "Karen feeds fake paper strips into an arcade ticket eater; the shredder spits confetti paper back out into her open mouth."),
    ("shoe_polishing_machine", "👞Karen Shoves Her Bare Foot In The Buffer — Foot Painted Black😂",
     "Karen jams her muddy barefoot into a shoe polishing machine's rotating bristles; it locks into industrial boot-buff mode and paints her foot black."),
]

q = queue_db.pipeline_load()
before = len(q)
existing = set()
for it in q:
    existing.add(str(it.get("topic", "")).lower())
    existing.add(str(it.get("title", "")).lower())
seen = set()
for topic, title, hook in ITEMS:
    if topic.lower() in existing or title.lower() in existing:
        print("DEDUP HIT (existing):", topic)
        sys.exit(2)
    if topic.lower() in seen:
        print("DEDUP HIT (batch):", topic)
        sys.exit(2)
    seen.add(topic.lower())

for topic, title, hook in ITEMS:
    scene = hook
    item = {
        "topic": topic,
        "hook": hook,
        "title": title,
        "prompt": (
            "Vertical 9:16 comedy short, about 10 seconds, photorealistic. "
            "A middle-aged woman 'Karen' with a bob haircut storms up to the machine and makes an entitled demand. "
            "Beat 1: Karen argues and forces her way. "
            "Beat 2: the machine's AI calmly enforces its rule. "
            f"Beat 3: instant karma — {scene} "
            "Fast cuts, exaggerated facial expressions, bright lighting, no burned-in subtitles except machine screen text."
        ),
        "description": hook,
        "tags": "Karen,InstantKarma,Shorts,AICustomerService,Comedy",
        "virality_score": 0.0,
        "series": "", "series_id": "", "series_name": "",
        "status": "selected", "slot": "",
        "urgent": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    q.append(item)
queue_db.pipeline_save(q)

q2 = queue_db.pipeline_load()
found = [i for i in q2 if i.get("topic") in {t for t, _, _ in ITEMS}]
print("items before/after:", before, len(q2))
print("found new:", len(found), "all selected:", all(i.get("status") == "selected" for i in found))
for i in found:
    print("-", i.get("topic"), "|", i.get("status"), "|", (i.get("_row_key") or "")[:8])
