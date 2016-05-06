#!/usr/bin/env python3
import urllib.request, urllib.error, urllib.parse
import xml.etree.ElementTree as ET
from binascii import hexlify, unhexlify
from PIL import Image
import os, ssl, json, unicodedata


# Client certs
ctr_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
ctr_context.load_cert_chain('ctr-common-1.crt', keyfile='ctr-common-1.key')
# XML from 3dsdb
# releases_xml = ET.parse('3dsreleases.xml')
# Dictionary of title keys
enc_title_keys = {}
with open('encTitleKeys.bin', 'rb') as f:
	n_entries = os.fstat(f.fileno()).st_size / 32
	f.seek(16, os.SEEK_SET)
	for i in range(int(n_entries)):
		f.seek(8, os.SEEK_CUR)
		title_id = f.read(8)
		title_key = f.read(16)
		enc_title_keys[hexlify(title_id).decode()] = hexlify(title_key).decode()


def get_id_pairs(ids, get_content_id = True):
	ret = [None] * len(ids)
	from_key = 'title_id' if get_content_id else 'ns_uid'
	to_key = 'title_id' if not get_content_id else 'ns_uid'
	
	ninja_url = 'https://ninja.ctr.shop.nintendo.net/ninja/ws/titles/id_pair'

	# URI length is limited, so need to break up large requests
	limit = 40
	if len(ids) > limit:
		ret = []
		ret += get_id_pairs(ids[:limit], get_content_id)
		ret += get_id_pairs(ids[limit:], get_content_id)
	else:
		ids = [x.upper() for x in ids]
		try:
			# key = 'title_id' if get_content_id else 'ns_uid'
			shop_request = urllib.request.Request(ninja_url + "?{}[]=".format(from_key) + ','.join(ids))
			shop_request.get_method = lambda: 'GET'
			response = urllib.request.urlopen(shop_request, context=ctr_context)
			xml = ET.fromstring(response.read().decode('UTF-8', 'replace'))
			for el in xml.findall('*/title_id_pair'):
				index = ids.index(el.find(from_key).text.upper())
				ret[index] = el.find(to_key).text.upper()
		except urllib.error.URLError as e:
			print(e)

	return ret;


def normalize_text(input):
	input = input.translate({ord(i):' ' for i in u"®™"})
	nfkd_form = unicodedata.normalize('NFKD', input)
	return u"".join([c for c in nfkd_form if not unicodedata.combining(c)]).lower()


def get_title_data(id, uid):
	# Returns array:
	# 0 - Title name
	# 1 - Title normalized for indexing
	# 2 - Content UID (as provided by arg)
	# 3 - Region list
	# 4 - Country code
	# 5 - Size
	# 6 - Icon url (to later be replaced by icon index)
	# 7 - Crypto seed (sometimes empty '')

	# samurai handles metadata actions, including getting a title's info
	# URL regions are by country instead of geographical regions... for some reason
	samurai_url = 'https://samurai.ctr.shop.nintendo.net/samurai/ws/'
	ec_url = 'https://ninja.ctr.shop.nintendo.net/ninja/ws/'
	region_array = ['JP', 'US', 'GB', 'DE', 'FR', 'ES', 'NL', 'IT'] # 'HK', 'TW', 'KR']
	eur_array = ['GB', 'DE', 'FR', 'ES', 'NL', 'IT']
	regions = []
	country_code = ''

	# try loop to figure out which region the title is from; there is no easy way to do this other than try them all
	for code in region_array:
		try:
			if code in eur_array and 'EU' in regions:
				continue
			title_request = urllib.request.Request(samurai_url + code + '/title/' + uid)
			titleResponse = urllib.request.urlopen(title_request, context=ctr_context)
			country_code = code
		except urllib.error.URLError as e:
			pass
		else:
			if code in eur_array:
				regions.append('EU')
			else:
				regions.append(code)
	if not regions:
		print("No region for {}?".format(id))
		return

	ec_response = urllib.request.urlopen(ec_url + country_code + '/title/' + uid + '/ec_info', context=ctr_context)	
	xml = ET.fromstring(titleResponse.read().decode('UTF-8', 'replace'))
	title_name = xml.find("*/name").text.replace('\n', ' ')
	try:
		icon_url = xml.find("*/icon_url").text.replace('\n', ' ')
	except:
		icon_url = -1

	xml = ET.fromstring(ec_response.read().decode('UTF-8', 'replace'))
	title_size = int(xml.find("*/content_size").text)
	try:
		crypto_seed = xml.find(".//external_seed").text
		print("Seed:", crypto_seed)
	except:
		crypto_seed = ''

	title_normalized = normalize_text(title_name)

	return [title_name, title_normalized, uid, regions, country_code, title_size, icon_url, crypto_seed]


# Fit 441 48x48 icons per 1024x1024 image
img_array = []
img_index = -1
icon_index = 0

def compile_texture(data):
	global img_index
	global icon_index

	if not os.path.exists("images"):
		os.makedirs("images")

	for title, title_data in data.items():
		if not title_data:
			print("No data? ", title)
		else:
			icon_url = title_data[6]
			if icon_url != -1:
				print(icon_url)
				res = urllib.request.urlopen(icon_url, context=ctr_context)
				img = Image.open(res)
				if img.size != (48, 48):
					img = img.resize((48, 48), 1)

				if icon_index > len(img_array) * 441 - 1:
					img_array.append(Image.new("RGB", (1024, 1024), "white"))
					img_index += 1

				x = int((icon_index % 441) / 21) * 48
				y = ((icon_index % 441) % 21) * 48

				img_array[img_index].paste(img, (x, y))
				data[title][6] = icon_index
				icon_index += 1

	for i, img in enumerate(img_array):
		img.save("images/icons{}.png".format(i))
		img.save("images/icons{}.jpg".format(i), quality=90)


def filter_titles(titles):
	ret = []
	tid_index = ['00040000']
	for title_id in titles:
		tid_high = title_id.upper()[:8]
		if tid_high in tid_index:
			ret.append(title_id)
	return ret


def scrape():
	data = {}
	titles = list(enc_title_keys.keys())
	titles = filter_titles(titles)

	uid_list = get_id_pairs(titles)

	for i, uid in enumerate(uid_list):
		if not uid:
			print("Failed to get uid for title id: " + titles[i])
		else:
			title_data = get_title_data(titles[i], uid)
			if title_data:
				data[titles[i]] = title_data
				print("Title {} out of {}: {} ({})".format(i+1, len(uid_list), title_data[0], title_data[1]))

	with open('data.json', 'w') as f:
		json.dump(data, f, separators=(',', ':'))


def texture_from_json():
	with open("data.json") as f:
		data = json.load(f)
	compile_texture(data)
	with open('data.json', 'w') as f:
		json.dump(data, f, separators=(',', ':'))


if __name__ == '__main__':
	scrape()
	texture_from_json()
