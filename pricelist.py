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

import json
import requests


def float_ecu(ecu):
    if ecu == "Variable":
        return 1
    return float(ecu)

def float_memory(mem):
    mem = mem.replace(',', '')
    return float(mem)

dynamic_data_text = requests.get('http://169.254.169.254/latest/dynamic/instance-identity/document').text
dd = json.loads(dynamic_data_text)
url = 'https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/%s/index.json' % dd['region']
pl_text = requests.get(url).text
pl = json.loads(pl_text)
terms = {p[0]: list(p[1].values())[0]['priceDimensions'] for p in pl['terms']['OnDemand'].items()}
instances = [(p['attributes']['instanceType'], p['sku'], p['attributes']) for p in pl['products'].values()
             if 'instanceType' in p['attributes'] and
             't1' not in p['attributes']['instanceType'] and
             'c1' not in p['attributes']['instanceType'] and
             'm1' not in p['attributes']['instanceType'] and
             'm2' not in p['attributes']['instanceType'] and
             p['attributes']['tenancy'] == 'Shared' and
             p['attributes']['operatingSystem'] == 'Linux']
priced = [(p[0], float(list(terms[p[1]].values())[0]['pricePerUnit']['USD']), p[2])
          for p in instances if p[1] in terms]
for p in list(sorted(priced, key=lambda p: p[1])):
    if float_ecu(p[2]['ecu']) == 0 or float_memory(p[2]['memory'][:-4]) == 0:
        continue
    print("%12s $%5.3f/hr $%4.0f/mo $%6.3f/ecu $%6.3f/GB vcpu=%2s ecu=%5.1f ram=%5s stor=%5s network=%s" %
          (p[0],
           p[1],
           p[1] * 730,
           p[1] / float_ecu(p[2]['ecu']),
           p[1] / float_memory(p[2]['memory'][:-4]),
           p[2]['vcpu'],
           float_ecu(p[2]['ecu']),
           float_memory(p[2]['memory'][:-4]),
           p[2]['storage'],
           p[2]['networkPerformance']))
