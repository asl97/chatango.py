import re
import sys
import time
import queue
import random
import socket
import _thread
import urllib.parse
import html.entities
import urllib.request

class InvalidCredentials(Exception): pass
class KickedOff(Exception): pass
class NotConnected(Exception): pass

# -----------------------------------------------------
# User class for holding user data in PMs and chatrooms
# -----------------------------------------------------

class chuser:
	ANON = 0
	TEMP = 1
	REGD = 2
	
	def __init__(self, username="", uid=None, umid=None, session=None, logintime=None, type=None, ip=None, ts=None):
		'''Holds user data information. displayname gives the person's
		username with the same capitalization as they typed in when
		they logged in. username returns their username in lowercase.
		You really don't need to worry about the rest.'''
		self._username = username
		self._ts = ts
		self.uid = int(uid) if uid != None else self._get_uid()
		self.umid = umid
		self.session = int(session) if session != None else session
		self.logintime = float(logintime) if logintime != None else logintime
		self.type = type
		self.ip = ip
	displayname = property(lambda x: x._username if (x.type == x.TEMP or x.type == x.REGD) else _anon_name(x.uid, x._ts))
	username = property(lambda x: x.displayname.lower(), lambda x, y: setattr(x, "_username", y))
		
	@staticmethod
	def _get_uid():
		return random.randrange(1000000000000000, 10000000000000000)

# -----------------------------------
# Empty shiz for holding message data
# -----------------------------------

class chmessage:
	HISTORY = 0
	NEW = 1
	def __init__(self, **kwargs):
		# This should hold: posttime, user, content, formatted, mid, umid, index
		for keyword in kwargs:
			setattr(self, keyword, kwargs[keyword])

# ---------
# PMS CLASS
# ---------

class pms:
	def __init__(self, username, password):
		self._username = username
		self._password = password
		self._connected = False
		self._reconnected = False
		self._logintime = time.time()
	
	# ------------------
	 # Interface methods
	
	def login(self):
		'''Login to PMs.'''
		# Get the auth token
		self._auth = _get_auth(self._username, self._password)
		if not self._auth:
			raise InvalidCredentials
		else:
			self._connected = True

		# Connect to chatango
		self._sock = socket.socket()
		self._sock.connect(("s2.chatango.com", 443))
		
		# Login
		self._send("tlogin", self._auth, 2, chuser._get_uid())
		
		# Set some personal shiz up
		self._q = queue.Queue()
		self._buffer = b''
		
		# Start shit
		_thread.start_new_thread(self._ping, ())
		_thread.start_new_thread(self._main, ())
		
		# Yay, nothing bad happened
		return True
	
	def disconnect(self):
		'''Disconnect from PMs.'''
		self._connected = False
		self._sock.close()

	def send(self, username, msg):
		'''Send msg to username.'''
		if isinstance(username, chuser):
			username = username.username
		msg = _to_str(msg).split("\n")
		msg = "<P>" + "</P><P>".join(msg) + "</P>"
		msg = re.sub("\t", " \x01 \x01 \x01 \x01", msg)
		self._send("msg", username, msg)
	
	def add_friend(self, username):
		'''Add someone to your friends list.'''
		self._send("connect", username.lower())
	
	def remove_friend(self, username):
		'''Remove someone from your friends list.'''
		self._send("delete", username.lower())
	
	def block(self, username):
		'''Block a user.'''
		self._send("block", username.lower())
	
	def unblock(self, username):
		'''Unblock a blocked user.'''
		self._send("unblock", username.lower())
	
	def get_event(self):
		'''Wait for the next event from pms. Events are
		dictionaries with an "event" key holding 1 of 3 values:
		"message", "login" or "logout".
		
		They have the following format:
		
		{
			"event": "message",
			"message": <class 'ch.chmessage'>,
			"pms": <class 'ch.pms'>,
			"reply": <function <lambda>>
		}
		{
			"event": "login",
			"username": username,
			"pms": <class 'ch.pms'>,
			"reply": <function <lambda>>
		}
		{
			"event": "logout",
			"username": username,
			"pms": <class 'ch.pms'>,
			"reply": <function <lambda>>
		}'''
		if not self._connected:
			raise NotConnected
		return self._q.get(timeout=1000000)
	
	# ---------------
	 # Helper methods
	
	def _ping(self):
		time.sleep(60)
		while self._connected:
			self._send("")
			time.sleep(60)
	
	def _main(self):
		while self._connected:
			event, args = self._recv()
			try:
				self._handle(event, args)
			except Exception as details:
				print(_get_tb())
	
	def _recv(self):
		if not self._connected:
			raise NotConnected
		while self._buffer.startswith(b'\x00'):
			self._buffer = self._buffer[1:]
		while not b'\x00' in self._buffer:
			successful = False
			while not successful:
				dc_count = 0
				next = self._sock.recv(8192)
				if next == b'':
					dc_count += 1
					if dc_count > 5:
						self._reconnect()
						continue
				self._buffer += next
				successful = True
		buffer = self._buffer.split(b'\x00')
		data = b'\r\n'
		while data == b'\r\n':
			data = buffer.pop(0)
		data = data.strip(b'\r\n').decode()
		self._buffer = b'\x00'.join(buffer)
		event = data.split(":")[0]
		args = data.split(":")[1:]
		if _DEBUG: print("PMS <<", data.encode())
		return [event, args]
	
	def _send(self, *args, terminator="\r\n\x00"):
		if not self._connected:
			raise NotConnected
		args = ":".join([_to_str(x) for x in args])
		args += terminator
		args = args.encode()
		sent = False
		while not sent:
			try:
				self._sock.send(args)
			except:
				self._reconnect()
			else:
				sent = True
		if _DEBUG: print("PMS >>", args)
	
	def _reconnect(self):
		# Get the auth token
		self._auth = _get_auth(self._username, self._password)
		
		# If the password has changed, gracefully exit, mimicking a Kicked-Off
		if not self._auth:
			self.diconnect()
			raise KickedOff
		
		# Connect to chatango
		self._sock = socket.socket()
		self._sock.connect(("s2.chatango.com", 443))
		
		# Login
		self._send("tlogin", self._auth, 2, self._user.uid)
		
		# Handle incoming messages differently, now
		self._reconnected = True
		self._buffer = b''
	
	# ------------------
	 # PMS Event Handler
	
	def _handle(self, event, args):
		if event == "time":
			self._logintime = float(args[0])
		elif event == "seller_name":
			username, self._uid = args
			self._uid = int(self._uid)
		elif event == "kickingoff":
			raise KickedOff
		elif event == "wloffline":
			username, logintime = args
			logintime = float(logintime)
			self._q.put({"event": "logout", "username": username, "pms": self, "reply": lambda x: self.send(username, x)})
		elif event == "wlonline":
			username, logintime = args
			logintime = float(logintime)
			self._q.put({"event": "login", "username": username, "pms": self, "reply": lambda x: self.send(username, x)})
		elif event == "msg" or (event == "msgoff" and self._reconnected == True):
			username, anon_uid, unknown, posttime, pro = args[:5]
			if username.startswith("*"):
				user_type = chuser.ANON
				username = "anon" + anon_uid[-4:]
			else:
				user_type = chuser.REGD
			posttime = float(posttime)
			raw = ":".join(args[5:])
			content = re.sub("</P><P>", "\n", raw)
			content = re.sub("<[^>]+>", "", content)
			msg = chmessage(posttime=posttime, formatted=raw, content=content, user=chuser(username=username, type=user_type))
			self._q.put({"event": "message", "message": msg, "pms": self, "reply": lambda x: self.send(username, x)})

class chatroom:
	def __init__(self, name):
		self.name = name.lower()
		self._mods = ()
		self._user = chuser()
		self._premium = False
		self._buffer = b''
		self._online = []
		self._history = []
		self._noid_messages = {}
		self._bw_regx = []
		self._connected = False
		self._reconnected = False
		self._ignore_messages = {}
		self.server = "s%i.chatango.com" % _get_server_num(self.name)
		# Register some default settings
		self.obey_badwords()
		self.keep_history(100)
		self.silent(False)
		self._font = {}
	font = property(lambda x: '<n%s/><f x%s%s="%s">' % (x._font.get("name") or "", x._font.get("size") or "", x._font.get("color") or "", _font_family.get(x._font.get("family")) or ""))
	
	# -------------------
	 # Connection methods
	
	def login(self, username=None, password=None):
		'''Login to the chatroom with the given credentials.
		If you provide:
		
		username, password - Login as a registered user
		username - Login with a temporary anon name
		zilch - Login as an anon'''
		if self._connected:
			self.logout()
		self._user.username = username
		self._user.password = password
		
		# Set the user type
		if username and password:
			self._user.type = chuser.REGD
		elif username:
			self._user.type = chuser.TEMP
		else:
			self._user.type = chuser.ANON

		if self._connected and self._user.username and self._user.password:
			self._send("blogin", self._user.displayname, self._user.password)
		elif self._connected and self._user.username:
			self._send("blogin", self._user.displayname)
		elif not self._connected:
			# Login for the first time
			self._sock = socket.socket()
			self._sock.connect((self.server, 443))
			self._connected = True
			
			# Send the login info
			if self._user.username and self._user.password:
				self._send("bauth", self.name, self._user.uid, self._user.displayname, self._user.password, terminator="\x00")
			else:
				self._send("bauth", self.name, terminator="\x00")
			
			# Set some personal shiz up
			self._session = random.randrange(10000,100000)
			self._q = queue.Queue()
			
			# Wait to get inited
			event = None
			while event != "inited":
				event, args = self._recv()
				self._handle(event, args)
			
			# Start shit
			_thread.start_new_thread(self._ping, (self._session,))
			_thread.start_new_thread(self._main, ())
			
		# Yay, nothing bad happened
		return True
	
	def logout(self):
		'''Logout. Go anon. Troll and shit.'''
		self._send("blogout")
	
	def disconnect(self):
		'''Disconnect from the chatroom.'''
		self._connected = False
		self._sock.close()
	
	def get_event(self):
		'''Wait for the next event from the chatroom. Events
		are dictionaries with an "event" key holding 1 of 4 values:
		"message", "login", "logout" or "nickchange".
		
		They have the following format:
		
		{
			"event": "message",
			"message": <class 'ch.chmessage'>,
			"room": <class 'ch.chatroom'>,
			"reply": <function <lambda>>
		}
		{
			"event": "login",
			"username": username,
			"user": <class 'ch.chuser'>,
			"room": <class 'ch.chatroom'>,
			"reply": <function <lambda>>
		}
		{
			"event": "logout",
			"username": username,
			"user": <class 'ch.chuser'>,
			"room": <class 'ch.chatroom'>,
			"reply": <function <lambda>>
		}
		{
			"event": "nickchange",
			"old": <class 'ch.chuser'>,
			"new": <class 'ch.chuser'>,
			"room": <class 'ch.chatroom'>,
			"reply": <function <lambda>>
		}'''
		if not self._connected:
			raise NotConnected
		return self._q.get(timeout=1000000)
	
	# ----------------------------
	 # Interface with the chatroom
	
	def say(self, msg, raw=True):
		'''Say something in the chatroom. If the raw option is True,
		html tags are embedded, else they are escaped.'''
		if not self._silenced:
			if not raw:
				msg = msg.replace("<", "&lt;")
			if self._obey_badwords:
				for word in self._bw_regx:
					msg = re.sub(word, "*", msg, re.IGNORECASE)
			if self._user.type == chuser.REGD:
				self._send("bmsg:t12r", self.font + _to_str(msg))
			else:
				self._send("bmsg:t12r", _to_str(msg))
	
	def find_user(self, key, online=True, history=True):
		'''Finds a user based on the lambda function key. Optionally
		search the list of online users and/or the message history.'''
		matches = []
		if online:
			for user in self._online:
				if key(user):
					matches.append(user)
		if history:
			for msg in self._history:
				if key(msg.user):
					matches.append(msg.user)
		return matches
	
	def is_online(self, username):
		'''Search the online list for a registered user.'''
		username.lower()
		if self.find_user(lambda x: x.username == username and x.type == chuser.REGD):
			return True
		else:
			return False
	
	def is_mod(self, username=None):
		'''See if a person is a mod in the chatroom. If no argument is
		provided, return whether or not the logged in user is a mod.'''
		if username == None and self._user.type == chuser.REGD:
			username = self._user.username
		elif not username:
			return False
		return bool(username.lower() in self._mods)

	def get_history(self, user):
		'''Takes a chuser object and returns that person's history
		in the chatroom.'''
		matches = []
		for msg in self._history:
			if msg.user.type == chuser.REGD and msg.user.username == user.username:
				matches.append(msg)
			elif msg.user.type == chuser.ANON and user.uid and msg.user.uid == user.uid:
				matches.append(msg)
			elif msg.user.type == chuser.TEMP and user.uid and [msg.user.uid, msg.user.username, msg.user.type] == [user.uid, user.username, user.type]:
				matches.append(msg)
		return matches
	
	# ------------------
	 # Moderator methods
	
	def ban(self, user):
		'''Takes a chuser object as an argument. And bans them. Derp.'''
		self._send("block", user.umid if user.umid else "", user.ip if user.ip else "", user.username)

	
	def unban(self, user):
		'''Under contruction. Kinda low priority. Leave faggots banned.'''
		if type(user)==type(""):
			self._send("removeblock", "", "", user)
		else:
			self._send("removeblock", user.umid if user.umid else "", user.ip if user.ip else "", user.username)

	
	def delete(self, msg):
		'''Takes a chmessage object as an argument, and deletes that
		single message.'''
		self._send("delmsg", msg.mid)
	
	def deleteall(self, username):
		'''Delete all posts made by someone with the given username.'''
		username = username.lower()
		matches = self.find_user(lambda x: x.username == username)
		for match in matches:
			self._send("delallmsg", match.umid)
	
	# -------------------------
	 # Manipulate room settings
	
	def keep_history(self, size):
		'''Control the number of messages to keep in the room's history.'''
		size = int(size)
		if size < 10:
			size = 10
		self._history_limit = size
	
	def obey_badwords(self, value=True):
		'''Control whether or not you can avoid word filters.'''
		self._obey_badwords = bool(value)
	
	def silent(self, mode=True):
		'''Set whether or not say() works. For turning off bots.'''
		self._silenced = bool(mode)
	
	def ignore(self, keyname, key):
		'''Add a function to be applied to new messages.
		If the function returns True, the message is ignored.
		
		Ex: ignore("anons", lambda x: x.user.type == chuser.ANON)'''
		if key != None and isinstance(key, type(lambda x: None)):
			self._ignore_messages[keyname] = key
	
	def unignore(self, keyname):
		'''Provide a keyname associated with an ignore function
		to stop applying that function to incoming messages.'''
		try:
			self._ignore_messages.pop(keyname)
		except:
			pass
	
	def set_font(self, size=None, family=None, color=None, name=None):
		'''Independently or simultaneously set the size, family,
		and color of the font to be displayed. Color and name must
		be html color codes.'''
		if isinstance(size, int):
			if self._premium and size > 22: 
				size = 22
			elif not self._premium and size > 14:
				size = 14
		if size != None: self._font["size"] = size
		if name != None: self._font["name"] = color
		if color != None: self._font["color"] = color
		if family != None: self._font["family"] = family
	
	def use_bg(self, value=True):
		'''Turn your background on or off.'''
		if self._premium:
			self._send("msgbg", 1 if bool(value) else 0)
			return True
		return False
	
	def set_bg(self, color="000000", image=None, transparency=None):
		'''Set your background. The color must be an html color code.
		The image parameter takes a boolean to turn the picture off or on.
		Transparency is a float less than one or an integer between 1-100.'''
		if self._premium:
			if color and len(color) == 1:
				color = color*6
			if color and len(color) == 3:
				color += color
			elif color and len(color) != 6:
				return False
			if transparency != None and abs(transparency) > 1:
				transparency = abs(transparency) / 100
			# Get the original settings
			letter1 = self._user.username[0]
			letter2 = self._user.username[1] if len(self._user.username) > 1 else self._user.username[0]
			data = urllib.request.urlopen("http://fp.chatango.com/profileimg/%s/%s/%s/msgbg.xml" % (letter1, letter2, self._user.username)).read().decode()
			data = dict([x.replace('"', '').split("=") for x in re.findall('(\w+=".*?")', data)[1:]])
			# Add the necessary shiz
			data["p"] = self._user.password
			data["lo"] = self._user.username
			if color: data["bgc"] = color
			if transparency != None: data["bgalp"] = abs(transparency) * 100
			if image != None: data["useimg"] = 1 if bool(image) else 0
			# Send the request
			data = urllib.parse.urlencode(data)
			try:
				urllib.request.urlopen("http://chatango.com/updatemsgbg", data).read()
			except:
				return False
			else:
				self._send("miu")
				return True
	
	# ---------------
	# Helper methods

	def _ping(self, session):
		time.sleep(60)
		while self._connected and session == self._session:	
			self._send("")
			time.sleep(60)
	
	def _main(self):
		while self._connected:
			event, args = self._recv()
			try:
				self._handle(event, args)
			except Exception as details:
				print(_get_tb())
	
	def _recv(self):
		if not self._connected:
			raise NotConnected
		while self._buffer.startswith(b'\x00'):
			self._buffer = self._buffer[1:]
		while not b'\x00' in self._buffer:
			successful = False
			while not successful:
				dc_count = 0
				try:
					next = self._sock.recv(8192)
				except socket.error:
					if self._connected:
						self._reconnect()
					else:
						return [None, None]
				if next == b'':
					dc_count += 1
					if dc_count > 5:
						self._reconnect()
						continue
				self._buffer += next
				successful = True
		buffer = self._buffer.split(b'\x00')
		data = b'\r\n'
		while data == b'\r\n':
			data = buffer.pop(0)
		data = data.strip(b'\r\n').decode()
		self._buffer = b'\x00'.join(buffer)
		event = data.split(":")[0]
		args = data.split(":")[1:]
		if _DEBUG: print(self.name, "<<", data.encode())
		return [event, args]
	
	def _send(self, *args, terminator="\r\n\x00"):
		if not self._connected:
			raise NotConnected
		args = ":".join([_to_str(x) for x in args])
		args += terminator
		args = args.encode()
		sent = False
		while not sent:
			try:
				self._sock.send(args)
			except:
				self._reconnect()
			else:
				sent = True
		if _DEBUG: print(self.name, ">>", args)
		
	def _reconnect(self):
		# Start a new connection
		self._sock = socket.socket()
		self._sock.connect((self.server, 443))
		
		# Send the login info
		if self._user.username and self._user.password:
			self._send("bauth", self.name, self._user.uid, self._user.username, self._user.password)
		else:
			self._send("bauth", self.name, terminator="\x00")
		
		# Handle messages differently evermore
		self._reconnected = True
		
		# Wait to get inited
		event = None
		while event != "inited":
			event, args = self._recv()
			self._handle(event, args)
	
	def _add_history(self, msg):
		if self._reconnected and msg.type == chmessage.HISTORY:
			# Go through the list and make sure that this message doesn't already exist
			append = True
			for message in self._history:
				if msg.mid == message.mid:
					append = False
			if append:
				msg.type = chmessage.NEW
				self._history.append(msg)
				self._history = sorted(self._history, key=lambda x: x.posttime)
			else:
				return
		else:
			self._history.append(msg)
		if msg.type == chmessage.HISTORY:
			self._history = sorted(self._history, key=lambda x: x.posttime)
		if msg.type == chmessage.NEW:
			addq = True
			for key in self._ignore_messages:
				func = self._ignore_messages.get(key)
				if func(msg):
					addq = False
					break
			if addq:
				self._q.put({"event": "message", "message": msg, "room": self, "reply": lambda x: self.say(x)})
		if len(self._history) > self._history_limit:
			self._history = self._history[-self._history_limit:]
	
	# -----------------------
	 # Chatroom Event Handler
	
	def _handle(self, event, args):
		if event == "ok":
			self._connected = True
			self.admin = args[0]
			self._user.uid = int(args[1])
			self._user.logintime = float(args[4])
			self._user.ip = args[5]
			self._mods = args[6].split(";")
			
			if args[2] == "M":
				self._user.type = chuser.REGD
			elif args[2] == "C":
				self._user.type = chuser.TEMP
			elif args[2] == "N":
				self._user.type = chuser.ANON
		elif event == "denied":
			self.disconnect()
		elif event == "inited":
			# Set up full name alerts and shit
			self._send("g_participants:start")
			# Get updated with the list of badwords
			self._send("getbannedwords")
			self._send("checkbannedwords")
			# Check for premium status
			self._send("getpremium", 1)
			# Log in with a temp name if need be
			if self._user.type == chuser.TEMP:
				self._send("blogin", self._user.displayname)
		elif event == "pwdok":
			self._user.type = chuser.REGD
			self._send("getpremium", 1)
		elif event == "aliasok":
			self._user.type = chuser.TEMP
			self._send("getpremium", 1)
		elif event == "logoutok":
			self._user.type = chuser.ANON
			self._send("getpremium", 1)
		elif event =="show_fw" or event == "show_tb":
			self._reconnect()
		elif event == "ubw":
			self._send("getbannedwords")
		elif event == "bw":
			bw = args[1]
			if not bw:
				self.badwords = []
			else:
				bw = urllib.parse.unquote(bw)
				bw = bw.strip(",").split(",")
				self.badwords = bw
				special_chars = "\\.^$*+?{}[]|()"
				self._bw_regx = []
				for x in range(0, len(self.badwords)):
					word = self.badwords[x]
					for char in special_chars:
						word = word.replace(char, "\\" + char)
					self._bw_regx.append(word)
		elif event == "premium":
			if args[1] != '0':
				self._premium = True
			else:
				self._premium = False
		elif event == "n":
			self.size = int(args[0], 16)
		elif event == "mods":
			self._mods = args
		elif event == "b" or event == "i":
			posttime, reg_name, tmp_name, uid, umid, index, ip, x = args[:8]
			msg = ":".join(args[8:])
			ts = re.findall("^<n(\d+)/>", msg)
			ts = ts[0] if ts else ""
			
			if reg_name == tmp_name == "":
				user_type = chuser.ANON
				username = ""
			elif reg_name == "":
				user_type = chuser.TEMP
				username = tmp_name
			else:
				user_type = chuser.REGD
				username = reg_name
			
			plaintext = re.sub("<[^>]+>", "", msg)
			plaintext = _unescape(plaintext)
			
			u = chuser(username=username, uid=uid, umid=umid, ip=ip, type=user_type, ts=ts)
			msg = chmessage(posttime=posttime, formatted=msg, content=plaintext, umid=umid, index=index, user=u)
			
			if event == "b":
				msg.type = chmessage.NEW
				self._noid_messages[msg.index] = msg
			elif event == "i":
				msg.type = chmessage.HISTORY
				del msg.index
				msg.mid = index
				self._add_history(msg)
		elif event == "u":
			index, mid = args
			msg = self._noid_messages.get(index)
			if msg:
				self._noid_messages.pop(msg.index)
				msg.mid = mid
				self._add_history(msg)
		elif event == "g_participants":
			args = ":".join(args)
			args = args.split(";")
			for infoz in args:
				session, logintime, uid, reg_name, tmp_name, null = infoz.split(":")
				
				# Determine the user type before doing anything else, reducing unecessary overhead
				if reg_name == tmp_name == "None":
					user_type = chuser.ANON
					username = ""
				elif reg_name == "None":
					user_type = chuser.TEMP
					username = tmp_name
				else:
					user_type = chuser.REGD
					username = reg_name
				
				if user_type == chuser.REGD:
					u = chuser(session=session, uid=uid, logintime=logintime, username=username, type=user_type)
					self._online.append(u)
		elif event == "participant":
			p_event, session, uid, reg_name, tmp_name, ip, logintime = args
			session = int(session)
			
			# Determine the user type before doing anything else, reducing unecessary overhead
			if reg_name == tmp_name == "None":
				user_type = chuser.ANON
				username = ""
			elif reg_name == "None":
				user_type = chuser.TEMP
				username = tmp_name
			else:
				user_type = chuser.REGD
				username = reg_name
			
			u = chuser(session=session, uid=uid, username=username, type=user_type, logintime=logintime, ip=ip)
			
			if p_event == "0":
				# The user logged out
				for user_ in self._online:
					if user_.session == session:
						self._online.remove(user_)
						if user_.type == chuser.REGD:
							self._q.put({"event": "logout", "username": u.username, "user": u, "room": self, "reply": lambda x: self.say(x)})
			elif p_event == "1":
				# The user logged in
				self._online.append(u)
				if u.type == chuser.REGD:
					self._q.put({"event": "login", "username": u.username, "user": u, "room": self, "reply": lambda x: self.say(x)})
			elif p_event == "2":
				for user_ in self._online:
					if user_.session == session:
						self._online.remove(user_)
						self._online.append(u)
						self._q.put({"event": "nickchange", "old": user_, "new": u, "room": self, "reply": lambda x: self.say(x)})

# --------------
# HELPER METHODS
# --------------

def _anon_name(uid, ts=None):
	uid = str(uid)[4:8]
	aid = ""
	ts = ts or "3452"
	for x in range(0, len(uid)):
		v4 = int(uid[x:x + 1])
		v3 = int(ts[x:x + 1])
		v2 = str(v4 + v3)
		aid += v2[len(v2) - 1:]
	return "Anon" + aid

def _get_server_num(name):
	roomname = name.lower()
	server = _server_weights['specials'].get(roomname)
	
	if not server:
		roomname = "q".join(roomname.split("_"))
		roomname = "q".join(roomname.split("-"))
		base36 = int(roomname[0:min(5, len(roomname))], 36)
		r10 = roomname[6:(6 + (min(3, (len(roomname) - 5))))]

		try:
			r7 = int(r10, 36)
		except:
			r7 = 1000
		else:
			if r7 <= 1000: r7 = 1000
		
		r4 = 0
		r5 = {}
		r6 = sum([x[1] for x in _server_weights["weights"]])
		
		for x in range(0, len(_server_weights["weights"])):
			r4 = r4 + _server_weights["weights"][x][1] / r6
			r5[_server_weights["weights"][x][0]] = r4
		
		for x in range(0, len(_server_weights["weights"])):
			if ((base36 % r7 / r7) <= r5[_server_weights["weights"][x][0]]):
				server = _server_weights["weights"][x][0];
				break
	
	return int(server)

def _get_auth(username, password):		
	data = urllib.parse.urlencode({'user_id' : username, 'password' : password, 'storecookie' : 'on', 'checkerrors' : 'yes'})
	while 1:
		try:
			headers = urllib.request.urlopen('http://chatango.com/login', data).headers.items()
		except:
			continue
		else:
			break
	auth = None
	for header in headers:
		if header[0] == 'Set-Cookie' and header[1].startswith('auth.chatango.com'):
			auth = header[1].split('=')[1].split(';')[0]
	if not auth:
		return None
	else:
		return auth

def _unescape(text):
	text = text.replace("&apos;", "'")
	text = text.replace("&quot;", '"')
	text = text.replace("&amp;", "&")
	def fixup(m):
		text = m.group(0)
		if text[:2] == "&#":
			# character reference
			try:
				if text[:3] == "&#x":
					return chr(int(text[3:-1], 16))
				else:
					return chr(int(text[2:-1]))
			except ValueError:
				pass
		else:
			# named entity
			try:
				text = chr(html.entities.name2codepoint[text[1:-1]])
			except KeyError:
				pass
		return text # leave as is
	return re.sub("&#?\w+;", fixup, text)

def _to_str(obj):
	'''Manipulate any data type to safely be a string'''
	if isinstance(obj, bytes):
		obj = obj.decode()
	return str(obj)

def _get_tb():
	try:
		et, ev, tb = sys.exc_info()
	except Exception as details:
		print(details)
	if not tb: return None
	while tb:
		line_no = tb.tb_lineno
		fn = tb.tb_frame.f_code.co_filename
		tb = tb.tb_next
	try:
		return "%s: %i: %s(%s)" % (fn, line_no, et.__name__, str(ev))
	except Exception as details:
		print(details)

def debug(value):
	global _DEBUG
	_DEBUG = bool(value)

_DEBUG = True
_server_weights = {'specials': {'mitvcanal': 56, 'animeultimacom': 34, 'cricket365live': 21, 'pokemonepisodeorg': 22, 'animelinkz': 20, 'sport24lt': 56, 'narutowire': 10, 'watchanimeonn': 22, 'cricvid-hitcric-': 51, 'narutochatt': 70, 'leeplarp': 27, 'stream2watch3': 56, 'ttvsports': 56, 'ver-anime': 8, 'vipstand': 21, 'eafangames': 56, 'soccerjumbo': 21, 'myfoxdfw': 67, 'kiiiikiii': 21, 'de-livechat': 5, 'rgsmotrisport': 51, 'dbzepisodeorg': 10, 'watch-dragonball': 8, 'peliculas-flv': 69, 'tvanimefreak': 54, 'tvtvanimefreak': 54}, 'weights' : [['5', 75], ['6', 75], ['7', 75], ['8', 75], ['16', 75], ['17', 75], ['18', 75], ['9', 95], ['11', 95], ['12', 95], ['13', 95], ['14', 95], ['15', 95], ['19', 110], ['23', 110], ['24', 110], ['25', 110], ['26', 110], ['28', 104], ['29', 104], ['30', 104], ['31', 104], ['32', 104], ['33', 104], ['35', 101], ['36', 101], ['37', 101], ['38', 101], ['39', 101], ['40', 101], ['41', 101], ['42', 101], ['43', 101], ['44', 101], ['45', 101], ['46', 101], ['47', 101], ['48', 101], ['49', 101], ['50', 101], ['52', 110], ['53', 110], ['55', 110], ['57', 110], ['58', 110], ['59', 110], ['60', 110], ['61', 110], ['62', 110], ['63', 110], ['64', 110], ['65', 110], ['66', 110], ['68', 95], ['71', 116], ['72', 116], ['73', 116], ['74', 116], ['75', 116], ['76', 116], ['77', 116], ['78', 116], ['79', 116], ['80', 116], ['81', 116], ['82', 116], ['83', 116], ['84', 116]]}
_font_family = {"arial": "0", "comic": "1", "georgia": "2", "handwriting": "3", "impact": "4", "palatino": "5", "papyrus": "6", "times": "7", "typewriter": "8"}
_font_family_nums = {'1': 'comic', '0': 'arial', '3': 'handwriting', '2': 'georgia', '5': 'palatino', '4': 'impact', '7': 'times', '6': 'papyrus', '8': 'typewriter'}
