#!/usr/bin/env python3
"""喜剧顾问第3轮：10个新动词展开~14条场景，写入 scenario_pool.json（备份+去重实测）。"""
import json, shutil, sys
from datetime import datetime

sys.path.insert(0, "/home/hatch/data/perpetua")
from formula_dedup import check_formula

POOL = "/home/hatch/data/perpetua/scenario_pool.json"
bak = POOL + ".bak-20261020-gaground3"
shutil.copy2(POOL, bak)
print("backup:", bak)

pool = json.load(open(POOL))

# (topic, hook, emoji_pair, tags)
new = [
    ("robot vacuum",
     "Karen's fluffy slipper gets catapulted sky-high by the robot vacuum's raised dustbin lid mid-rant",
     ["🤖", "🥿"], "vacuum,slipper,catapult,clean"),
    ("AI self-checkout kiosk",
     "The self-checkout scanner blasts reverse suction and glues Karen's wig flat onto the glass screen",
     ["🛒", "💇"], "checkout,scanner,suction,wig"),
    ("smart parking meter",
     "The parking meter's cable arm sweeps low and trips Karen into a stumbling lurch",
     ["🅿️", "🤸"], "parking,meter,trip,cable"),
    ("smart security gate",
     "The security gate's floor bar extends fast and trips Karen as she storms through",
     ["🚧", "🤸"], "gate,trip,bar,storm"),
    ("smart air purifier",
     "The air purifier pops a giant filter net over Karen, trapping her head-to-toe like a bird cage",
     ["🌬️", "🕸️"], "purifier,net,trap,filter"),
    ("smart fridge",
     "The smart fridge blasts dry-ice fog that flash-freezes Karen's hair and nails into frosty sculptures",
     ["🧊", "❄️"], "fridge,freeze,fog,frost"),
    ("smart parcel locker",
     "The parcel locker's doors push forward and sandwich Karen between foam pads, immobilized",
     ["📦", "🥪"], "locker,sandwich,foam,trapped"),
    ("smart revolving door",
     "The revolving door spins at max speed and sweeps ranting Karen smoothly out the entrance",
     ["🚪", "🌀"], "door,spin,sweep,entrance"),
    ("smart doorbell",
     "The doorbell camera pops out on its spring and knocks Karen's oversized sunglasses clean off",
     ["🔔", "🕶️"], "doorbell,camera,spring,sunglasses"),
    ("smart security camera",
     "The security camera detaches from its mount and bonks Karen's forehead as she yells at it",
     ["📷", "🤕"], "camera,bonk,forehead,mount"),
    ("self checkout kiosk",
     "The checkout conveyor belt rockets forward and flings Karen's giant tote bag off-screen like a frisbee",
     ["🛒", "🥏"], "conveyor,fling,bag,frisbee"),
    ("smart speaker",
     "The smart speaker's LED ring strobes disco-fast with reversing beeps until dizzy Karen staggers",
     ["🔊", "💫"], "speaker,strobe,dizzy,led"),
    ("AI elevator",
     "The elevator's ceiling light strobes and its arrival chime blares until Karen staggers out dizzy",
     ["🛗", "💫"], "elevator,strobe,dizzy,chime"),
    ("smart toaster",
     "The smart toaster launches Karen's bagel like a catapult straight into her ranting face",
     ["🍞", "🎯"], "toaster,bagel,catapult,face"),
]

added = []
for topic, hook, emoji, tags in new:
    is_dup, reason, detail = check_formula(topic, hook, "")
    if is_dup:
        print("BLOCKED:", topic, "|", hook[:50], "|", reason)
        continue
    added.append({"emoji_pair": emoji, "hook": hook, "tags": tags, "topic": topic})

pool.extend(added)
with open(POOL, "w", encoding="utf-8") as f:
    json.dump(pool, f, ensure_ascii=False, indent=2)

# 校验
reloaded = json.load(open(POOL))
print("added:", len(added), "| pool total:", len(reloaded))
print("new verbs now excluded (59+10=69): catapult vacuum trip smother freeze entomb sweep dislodge fling blink")
