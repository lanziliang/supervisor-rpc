#!/usr/bin/python
#coding: utf-8

import supervisor.xmlrpc
import xmlrpclib
import MySQLdb
import time, json
import ConfigParser
import os, sys
import re, urllib2
import threading

PROJECT_PATH = os.path.realpath(os.path.dirname(__file__))
config = ConfigParser.ConfigParser()
config.read(os.path.join(PROJECT_PATH, 'config.ini'))

dbhost = config.get("mysql", "host")
dbport = config.getint("mysql", "port")
dbuser = config.get("mysql", "user")
dbpasswd = config.get("mysql", "passwd")
dbdb = config.get("mysql", "db")
dbcharset = config.get("mysql", "charset")

xmlhost = config.get("xmlrpc", "host")
xmlurl = config.get("xmlrpc", "url")

processStr = config.get("process", "names")
processList = json.loads(processStr)

def getIp():
	ip = ""
	while ip == "":
		try:
			ip = re.search('\d+\.\d+\.\d+\.\d+', urllib2.urlopen("http://city.ip138.com/ip2city.asp").read()).group(0)
		except:
			try:
				ip = re.search('\d+\.\d+\.\d+\.\d+', urllib2.urlopen("http://www.whereismyip.com").read()).group(0)
			except:
				try:
					ip = re.search('\d+\.\d+\.\d+\.\d+', urllib2.urlopen("http://169.254.169.254/latest/meta-data/public-ipv4").read()).group(0)
				except:
					ip = ""
	return ip

srvIP = getIp()
# print srvIP


def getPinfo(n):
	server = xmlrpclib.ServerProxy(xmlhost, transport = supervisor.xmlrpc.SupervisorTransport(None, None, xmlurl))
	try:
		pInfo = server.supervisor.getProcessInfo(n)
	except Exception, e:
		raise Exception("supervisor xmlrpc errors"+str(e))
	finally:
		server.close
	return pInfo

def getPerrlogs(n):
	server = xmlrpclib.ServerProxy(xmlhost, transport = supervisor.xmlrpc.SupervisorTransport(None, None, xmlurl))
	try:
		logs = server.supervisor.readProcessStderrLog(n, 0, 0)
	except Exception, e:
		raise Exception("supervisor xmlrpc errors"+str(e))
	finally:
		server.close
	return logs

def getLastTime(k):
	lastTime = 1262304000
	if os.path.exists(os.path.join(PROJECT_PATH, 'lasttime' )) == False:
		os.mkdir(os.path.join(PROJECT_PATH, 'lasttime' )) 
	filePath = os.path.join(PROJECT_PATH, 'lasttime/' + k)
	if os.path.exists(filePath) == False:
		fp = open(filePath, 'w')
		fp.write(str(lastTime))
		fp.close()
	fp = open(filePath, 'r+')
	try:
		lastTime = fp.read()
		lastTime = int(lastTime)
	except Exception, e:
		raise Exception("get last time err:" + str(e))
	finally:
		fp.close()
	return lastTime

def setLastTime(k, v):
	filePath = os.path.join(PROJECT_PATH, 'lasttime/' + k)
	fp = open(filePath, 'r+')
	try:
		fp.write(str(v))
	except Exception, e:
		raise Exception("set last time err:" + str(e))
	finally:
		fp.close()
	return

def addLog(n, t, l, lt, ct, ip):
	conn = MySQLdb.connect(
		host = dbhost,
		port = dbport,
		user = dbuser,
		passwd = dbpasswd,
		db = dbdb,
		charset = dbcharset,
	)
	cur = conn.cursor()
	try:
		ld = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(lt))
		cd = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ct))
		sqlStr = "insert into server_status_logs (process_name, type, log_content, last_date, create_date, ip) values (%s, %s, %s, %s, %s, %s)"
		cur.execute(sqlStr, (n, t, l, ld, cd, ip))
		conn.commit()
	except Exception, e:
		raise Exception("MySQL errors:"+str(e))
	finally:
		cur.close()
		conn.close()
	return

def listenStart(pName, name):
	try:
		startKey = srvIP + pName + '_start'
		while 1:
			pInfo = getPinfo(pName)
			if pInfo['state'] == 10:
				lastStartTime = getLastTime(startKey)
				if pInfo['start'] > lastStartTime:
					# print pInfo
					setLastTime(startKey, pInfo['start'])
					t = threading.Thread(target = addLog, args = (name, 1, '', lastStartTime, pInfo['start'], srvIP))
					t.setDaemon(True)
					t.start()
	except Exception, e:
		print "Listen process "+pName+" start status errors:"+str(e)
		return

def listenStop(pName, name):
	try:
		stopKey = srvIP + pName + '_stop'
		while 1:
			pInfo = getPinfo(pName)
			if pInfo['state'] == 100 or pInfo['state'] == 0 or pInfo['state'] == 40:
				lastStopTime = getLastTime(stopKey)
				if pInfo['stop'] > lastStopTime:
					# print pInfo
					setLastTime(stopKey, pInfo['stop'])
					t = threading.Thread(target = addLog, args = (name, 0, '', lastStopTime, pInfo['now'], srvIP))
					t.setDaemon(True)
					t.start()
	except Exception, e:
		print "Listen process "+pName+" stop status errors:"+str(e)
		return

def listenExit(pName, name):
	try:
		exitKey = srvIP + pName + '_exit'
		while 1:
			pInfo = getPinfo(pName)
			if pInfo['state'] == 200:
				lastExitTime = getLastTime(exitKey)
				if pInfo['stop'] > lastExitTime:
					# print pInfo
					setLastTime(exitKey, pInfo['stop'])
					logs = getPerrlogs(pName)
					index = logs.rfind('panic')
					t = threading.Thread(target = addLog, args = (name, 2, logs[index:], lastExitTime, pInfo['now'], srvIP))
					t.setDaemon(True)
					t.start()
	except Exception, e:
		print "Listen process "+pName+" fatal status errors:"+str(e)
		return


if __name__ == '__main__':
	threads = []

	for k, v in processList.items():
		name = v
		if v == "" :
			name = k
		threads.append(threading.Thread(target = listenStart, args = (k, name)))
		threads.append(threading.Thread(target = listenStop, args = (k, name)))
		threads.append(threading.Thread(target = listenExit, args = (k, name)))

	for t in threads:
		t.setDaemon(True) #主线程退出后，杀掉子线程
		t.start()

	# 一旦有线程结束， 就退出主线程（主线程用supervisor守护）
	while 1:
		for t in threads:
			alive = t.isAlive()
			if alive == False:
				sys.exit()