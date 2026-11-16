#!/bin/sh
# The one command that proves plotpointe-animate works. Exit 0 = pass, anything else = fail.
# Written or approved by Nick. Agents may run it, never edit it.
# Put real checks in checks/ and call them from here.
cd "$(dirname "$0")" || exit 1
python3 checks/check_page.py
