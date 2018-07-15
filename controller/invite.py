# Copyright (c) 2016-2018 David Preece - davep@polymath.tech, All rights reserved.
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
"""Inviting users"""

import logging
import re
import smtplib
from email.message import EmailMessage

from model.state import ClusterGlobalState
from awsornot.log import LogHandler
from broker import LaksaIdentity


class Invite:
    def __init__(self):
        # set up environment
        logging.basicConfig()
        self.aws = ClusterGlobalState(noserver=True)
        self.log = LogHandler('20ft', 'broker')
        self.iden = LaksaIdentity()

    def stop(self):
        self.iden.stop()
        self.log.stop()
        self.aws.stop()

    def invite(self, email, domain):
        # returns success, reason
        if not re.match(r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)", email):
            return False, "Email address didn't validate: " + email

        # does the user already have an account?
        try:
            self.iden.raise_for_no_user(email)
            return False, "User already has an account"
        except ValueError:
            pass  # we're expecting to not get a result

        # create the invite token
        token = self.iden.create_pending_user(email)

        # create the email
        msg = EmailMessage()
        msg['Subject'] = "Invite to 20ft container infrastructure at " + domain
        msg['From'] = 'admin@' + domain
        msg['To'] = email
        msg.set_content("""
        You have been invited to use the 20ft container infrastructure at %s.
        To get up and going quickly, head to the quickstart documentation
        (http://docs.20ft.nz/quick.html) and use the login command:

        tfnz %s %s

        If all goes well you should see a message: Created OK for: %s
        If you get 'Authentication failed' this means you have pre-existing credentials in ~/.20ft,
        rm ~/.20ft/default_location and try again.
        If all else fails, reply to this email and an actual human will help.

        You may wish to ensure everything is up to date:
        ...sudo pip3 install tfnz --upgrade

        Man pages can be installed with:
        ...curl -s https://20ft.nz/shell | sh

        Full documentation is on the web:
        ...http://docs.20ft.nz/

        To move your credentials in future, run 
        ....tfacctbak
        and paste the resulting script into the terminal of the destination machine. 

        Enjoy!
            """ % (domain, domain, token, domain))

        # send
        s = smtplib.SMTP_SSL('mail.20ft.nz')
        with open('smtp_password') as f:
            s.login('invites', f.read().rstrip('\r\n'))
        s.send_message(msg)
        s.quit()
        return True, "Sent invite (via SMTP) to: " + email

