import json, urllib.request
d=json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/platform_matrix', timeout=20))
print(d.get('updated_at'))
for k,p in d['platforms'].items():
    print(k, p['status'], p.get('synced_at'))
