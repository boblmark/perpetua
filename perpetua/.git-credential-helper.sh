#!/bin/bash
# git credential helper：从 authd 保险库实时取 GitHub token，永不落盘。
# 用法：git config credential.helper "!/bin/bash /home/hatch/data/perpetua/.git-credential-helper.sh"
if [ "$1" = "get" ]; then
  TOKEN=$(python3 -c "
import sys
for _p in ('/opt/hatch/skills/skill-creator/bin',
           '/opt/hatch/workflow-skills/custom-connector-setup/bin',
           '/opt/muse/skills/custom-connector-setup/bin'):
    import os
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
from dynamic_credentials import dynamic_credential_entry
print(dynamic_credential_entry('custom.github')['surrogate'])
" 2>/dev/null)
  if [ -n "$TOKEN" ]; then
    echo "username=x-access-token"
    echo "password=$TOKEN"
  fi
fi
# store/erase：不做任何持久化
exit 0
