from pathlib import Path


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"target not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


path = Path("opportunity_alerts.py")
text = path.read_text(encoding="utf-8")
if "import random\n" not in text:
    text = text.replace("import os\n", "import os\nimport random\n", 1)
    path.write_text(text, encoding="utf-8")

old = '''def _selected_mid_message(message):\n    return str(message).replace(\n        "🔥 **中穴予想｜",\n        "🚨 **厳選中穴予想｜",\n        1,\n    )\n'''
new = '''def _selected_mid_message(message):\n    intros = (\n        "中穴狙いの中でも、条件が揃った一戦を厳選。",\n        "今日はここ。中穴狙いで勝負したい一戦です。",\n        "期待値・展開ともに狙える中穴レースを厳選。",\n        "数ある中穴候補から、ひとつ上の勝負レースを選定。",\n        "中穴狙いなら、ここは押さえておきたい一戦。",\n    )\n    body = str(message).replace(\n        "🔥 **中穴予想｜",\n        "🚨 **厳選中穴予想｜",\n        1,\n    )\n    return f"{random.choice(intros)}\\n\\n{body}"\n'''
replace_once(path, old, new)
print("selected mid-odds random intro patched")
