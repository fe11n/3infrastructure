import argparse
import json
import os
import requests
import sys
import yaml
from prettytable import PrettyTable


parser = argparse.ArgumentParser(
    description='The script is used to moderate the text and image of Pull Request.To run the script, you must '
                'provide owner(-o),repo(-r) and number(-n) of a pull request. You can also declare a list which limit '
                'the types of files you need to moderate by suffix(-s).') 
parser.add_argument('-o', '--owner', help='owner of pull request', required=True)
parser.add_argument('-r', '--repo', help='repo of pull request', required=True)
parser.add_argument('-n', '--number', help='number of pull request', type=int, required=True)
parser.add_argument('-s', '--suffix', help='limit the suffix of files to moderate', nargs='*')
args = parser.parse_args()
owner = args.owner
repo = args.repo
number = args.number
suffix = args.suffix

account_username = os.getenv('_ACCOUNT_USERNAME', '')
region = os.getenv('REGION', '')
iam_username = os.getenv('IAM_USERNAME', '')
iam_password = os.getenv('IAM_PASSWORD', '')

fp = open('categories.yaml', 'r')
content = yaml.load(fp.read(), Loader=yaml.Loader)
text_suffixes = content['text_suffixes']
text_categories = content['text_categories']
image_suffixes = content['image_suffixes']
image_categories = content['image_categories']
image_ad_categories = content['image_ad_categories']
fp.close()


def get_token():
    url = "https://iam.cn-north-4.myhuaweicloud.com/v3/auth/tokens"
    headers = {
        'Content-Type': 'application/json'
    }
    data = {
        "auth": {
            "identity": {
                "methods": [
                    "password"
                ],
                "password": {
                    "user": {
                        "domain": {
                            "name": account_username
                        },
                        "name": iam_username,
                        "password": iam_password
                    }
                }
            },
            "scope": {
                "project": {
                    "name": region
                }
            }
        }
    }

    r = requests.post(url=url, headers=headers, data=json.dumps(data))
    if r.status_code == 201:
        token = r.headers['X-Subject-Token']
        return token
    else:
        print(r.json())
        return


def moderate_text(text):
    token = get_token()
    if not token:
        print('token required')
        exit()
    url = 'https://moderation.{}.myhuaweicloud.com/v1.0/moderation/text'.format(region)
    headers = {
        'Content-Type': 'application/json',
        'X-Auth-Token': token
    }
    data = {
        "categories": text_categories,
        "items": [
            {
                "text": text,
                "type": "content"
            }
        ]
    }
    r = requests.post(url=url, headers=headers, data=json.dumps(data))
    return r.json()


def moderate_image(img):
    token = get_token()
    if not token:
        print('token required')
        exit()
    url = 'https://moderation.{}.myhuaweicloud.com/v1.0/moderation/image'.format(region)
    headers = {
        'Content-Type': 'application/json',
        'X-Auth-Token': token
    }
    data = {
        "url": img,
        "image": "",
        "categories": image_categories, 
        "ad_categories": image_ad_categories,
        "threshold": ""
    }
    r = requests.post(url, headers=headers, data=json.dumps(data))
    return r.json()


def deal_with_text(file_name, s, pt, error):
    pieces = []
    while len(s) > 0:
        pieces.append(s[:5000])
        s = s[5000:]
    for piece in pieces:
        res = moderate_text(piece)
        if res['result']['suggestion'] != 'pass':
            sensities = res['result']['detail']['sensitive_words']
            pt.add_row([file_name, "counts of sensitive words: {}".format({x: sensities.count(x) for x in sensities})])
            error += 1
    return error


def deal_with_image(file_name, pt, error, owner, repo, number):
    r = requests.get('https://gitee.com/api/v5/repos/{}/{}/pulls/{}'.format(owner, repo, number))
    giteeid = r.json()['user']['login']
    branch = r.json()['head']['ref']
    image_url = 'https://gitee.com/{}/{}/raw/{}/{}'.format(giteeid, repo, branch, file_name)
    res = moderate_image(image_url)
    print(res)
    pt.add_row([file_name, "detail: {}".format(res['result']['category_suggestions'])])
    return error


def main(owner, repo, number):
    url = 'https://gitee.com/{}/{}/pulls/{}.diff'.format(owner, repo, number)
    r = requests.get(url)
    content = r.text
    slices = content.split('diff --git ')[1:]
    error = 0
    pt = PrettyTable(['File Name', 'Attentions'])
    for s in slices:
        file_name = s.split()[0].split('/', 1)[-1]
        if suffix:
            if file_name.split('.')[-1] not in suffix:
                continue
            if file_name.split('.')[-1] in text_suffixes:
                error = deal_with_text(file_name, s, pt, error)
            if file_name.split('.')[-1] in image_suffixes:
                if file_name.endswith('.gif') and os.path.getsize(file_name) > 200 * 1024:
                    print('{}: Gif file over 200Kb needs to be converted to video'.format(file_name))
                    pt.add_row([file_name, 'Gif file over 200Kb needs to be converted to video'])
                    error += 1
                elif os.path.getsize(filename=file_name) > 500 * 1024:
                    print('{}: Images larger than 500Kb are not allowed'.format(file_name))
                    pt.add_row([file_name, 'Images larger than 500Kb are not allowed'])
                    error += 1
                else:
                    error = deal_with_image(file_name, pt, error, owner, repo, number)
        else:
            if file_name.split('.')[-1] in text_suffixes:
                error = deal_with_text(file_name, s, pt, error)
            if file_name.split('.')[-1] in image_suffixes:
                if file_name.endswith('.gif') and os.path.getsize(file_name) > 200 * 1024:
                    print('{}: Gif file over 200Kb needs to be converted to video'.format(file_name))
                    pt.add_row([file_name, 'Gif file over 200Kb needs to be converted to video'])
                    error += 1
                elif os.path.getsize(filename=file_name) > 500 * 1024:
                    print('{}: Images larger than 500Kb are not allowed'.format(file_name))
                    pt.add_row([file_name, 'Images larger than 500Kb are not allowed'])
                    error += 1
                else:
                    error = deal_with_image(file_name, pt, error, owner, repo, number)
    if error:
        print('The table below show attentions you may review after moderation.')
        print(pt)
    else:
        print('moderation pass :)')
    return error


if __name__ == '__main__':
    err = main(owner, repo, number)
    sys.exit(err)
