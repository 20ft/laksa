# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/

import sys
from controller.invite import Invite

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: invite-user user-email location-fqdn")
        exit(1)

    email = sys.argv[1]
    domain = sys.argv[2]

    inv = Invite()
    success = False
    try:
        success, words = inv.invite(email, domain)
        print(words)
    finally:
        inv.stop()
    exit(0 if success else 1)
