# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/
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
