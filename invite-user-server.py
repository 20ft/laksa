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
"""Accepting user signups via mailchimp"""

from bottle import Bottle, request
from controller.invite import Invite

# Mailchimp webhook specification:
#
# {
# 	"url": "http://sydney.20ft.nz:8123/",
# 	"events": {
# 		"subscribe": True
# 	},
# 	"sources": {
# 		"user": True,
# 		"admin": True,
# 		"api": True
# 	}
# }

invite = Invite()
http_server = Bottle()


class InviteUserServer:
    # it likes to post the event twice
    already = set()

    @staticmethod
    @http_server.post('/')
    def go():
        email = request.POST['data[email]']
        if email in InviteUserServer.already:
            return
        InviteUserServer.already.add(email)
        invite.invite(email, 'sydney.20ft.nz')


http_server.run(host='0.0.0.0', port=8123)
