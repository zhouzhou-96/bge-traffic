"""Copyright (c) 2015 Francesco Mastellone
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

"""
"east": increasing x
"north": increasing y
"""

import time
from math import atan2
from random import random, choice

import bge
from bge import logic

from cityengine import LinearWay, BezierWay, Intersection, Vehicle

import sys
sys.path.append('/usr/local/lib/python2.7/dist-packages')
import paho.mqtt.client as mqtt

import threading
import socket
from threading import Timer

import requests
import logging

cell_size = 2.
cs = cell_size / 2.
ct = cell_size / 4.

global z
z = 0
global a
a=0

scene = logic.getCurrentScene()

class Road(bge.types.KX_GameObject):
    def link(self):
        self.adj_e = scene.objects[self['adj_e']] if self['adj_e'] and 'Road' in scene.objects[self['adj_e']].name else None
        self.adj_w = scene.objects[self['adj_w']] if self['adj_w'] and 'Road' in scene.objects[self['adj_w']].name else None
        self.adj_n = scene.objects[self['adj_n']] if self['adj_n'] and 'Road' in scene.objects[self['adj_n']].name else None
        self.adj_s = scene.objects[self['adj_s']] if self['adj_s'] and 'Road' in scene.objects[self['adj_s']].name else None
        self.adj = list(a for a in (self.adj_e, self.adj_w, self.adj_n, self.adj_s) if a)

    def update(self, dt):
        pass

class RoadH(Road):
    def __init__(self, old_owner):
        x, y, _ = self.worldPosition
        e = x + cs
        w = x - cs
        n = y + ct
        s = y - ct
        self.way_e = LinearWay(w, s, e, s) # "way east": goes from west to east
        self.way_w = LinearWay(e, n, w, n)
        self.ways = self.way_e, self.way_w

    def link_ways(self):
        if self.adj_e:
            self.way_e.to.append(self.adj_e.way_e)
            self.adj_e.way_w.to.append(self.way_w)
        if self.adj_w:
            self.way_w.to.append(self.adj_w.way_w)
            self.adj_w.way_e.to.append(self.way_e)

        if not self.adj_w:
            M.spawns.append(self.way_e)
        if not self.adj_e:
            M.spawns.append(self.way_w)

class RoadV(Road):
    def __init__(self, old_owner):
        x, y, _ = self.worldPosition
        e = x + ct
        w = x - ct
        n = y + cs
        s = y - cs
        self.way_n = LinearWay(e, s, e, n)
        self.way_s = LinearWay(w, n, w, s)
        self.ways = self.way_n, self.way_s

    def link_ways(self):
        if self.adj_n:
            self.way_n.to.append(self.adj_n.way_n)
            self.adj_n.way_s.to.append(self.way_s)
        if self.adj_s:
            self.way_s.to.append(self.adj_s.way_s)
            self.adj_s.way_n.to.append(self.way_n)

        if not self.adj_s:
            M.spawns.append(self.way_n)
        if not self.adj_n:
            M.spawns.append(self.way_s)



def line(p1, p2):
    A = (p1[1] - p2[1])
    B = (p2[0] - p1[0])
    C = (p1[0]*p2[1] - p2[0]*p1[1])
    return A, B, -C

def intersection(L1, L2):
    D  = L1[0] * L2[1] - L1[1] * L2[0]
    Dx = L1[2] * L2[1] - L1[1] * L2[2]
    Dy = L1[0] * L2[2] - L1[2] * L2[0]
    if D != 0:
        x = Dx / D
        y = Dy / D
        return x,y
    else:
        return False

def make_curve_between(A, B, *args, **kwargs):
    """Makes a BezierWay linking LinearWay A and LinearWay B"""
    x, y = intersection(line((A.x0, A.y0), (A.x1, A.y1)),
                        line((B.x0, B.y0), (B.x1, B.y1)))
    W = BezierWay(A.x1, A.y1, x, y, x, y, B.x0, B.y0, *args, **kwargs)
    A.to.append(W)
    W.to.append(B)

class RoadX(Road):
    def __init__(self, old_owner):
        x, y, _ = self.worldPosition

        # Horizontal
        e = x + cs
        w = x - cs
        n = y + ct
        s = y - ct
        self.way_e = LinearWay(w, s, e, s) # "way east": goes from west to east
        self.way_w = LinearWay(e, n, w, n)
        # Vertical
        e = x + ct
        w = x - ct
        n = y + cs
        s = y - cs
        self.way_n = LinearWay(e, s, e, n)
        self.way_s = LinearWay(w, n, w, s)

    def link_ways(self):
        inputs = []
        if self.adj_e:
            inputs.append(self.adj_e.way_w)
        if self.adj_w:
            inputs.append(self.adj_w.way_e)
        if self.adj_n:
            inputs.append(self.adj_n.way_s)
        if self.adj_s:
            inputs.append(self.adj_s.way_n)

        # Intersections
        self.intersection = Intersection(inputs)

        joints = []
        if self.adj_s and self.adj_e: # s to e
            joints.append((self.adj_s.way_n, self.adj_e.way_e))

        if self.adj_s and self.adj_w: # s to w
            joints.append((self.adj_s.way_n, self.adj_w.way_w))

        if self.adj_w and self.adj_s: # and so on
            joints.append((self.adj_w.way_e, self.adj_s.way_s))

        if self.adj_w and self.adj_n:
            joints.append((self.adj_w.way_e, self.adj_n.way_n))

        if self.adj_n and self.adj_w:
            joints.append((self.adj_n.way_s, self.adj_w.way_w))

        if self.adj_n and self.adj_e:
            joints.append((self.adj_n.way_s, self.adj_e.way_e))

        if self.adj_e and self.adj_n:
            joints.append((self.adj_e.way_w, self.adj_n.way_n))

        if self.adj_e and self.adj_s:
            joints.append((self.adj_e.way_w, self.adj_s.way_s))

        for A, B in joints:
            make_curve_between(A, B, speed_limit=10./8.)

    def update(self, dt):
        self.intersection.update(dt)



class Car(bge.types.KX_GameObject, Vehicle):
    length = .7
    acceleration = 7.84 / 9.
    deceleration = 7.84 / 2. # Max possible with g=9.81m/s, roadfrictioncoeff=.8
    ID = 0
    def __init__(self, old_owner, way):
        Vehicle.__init__(self, way)
        self.speed_mul = 1. - random() * .2
        self.rot = 0.

    def get_x(self):
        return self.worldPosition.x
    def set_x(self, x):
        self.worldPosition.x = x
    x = property(get_x, set_x)

    def get_y(self):
        return self.worldPosition.y
    def set_y(self, y):
        self.worldPosition.y = y
    y = property(get_y, set_y)

    def update(self, dt):
        Vehicle.update(self, dt)

        dx = self.x - self.xp
        dy = self.y - self.yp
        if dx*dx + dy*dy > 0.:
            self.rot = atan2(dy, dx)
        # print('*********************************')
        # print(self.worldPosition.x)
        # print('*********************************')

        str_pos=str(self.worldPosition.x)+'_'+str(self.worldPosition.y)
        #m.mqtt_client.publish('get_pos',str_pos)

        xyz = self.localOrientation.to_euler()
        xyz[2] = self.rot
        self.localOrientation = xyz.to_matrix()
        #print('>>>>>>>>>22222222>>>>>>>>>>>>>')
        #print(self.localOrientation)
        #print('>>>>>>>>>>>222222222>>>>>>>>>>>')

    def on_dead_end(self):
        M.cars.remove(self)
        self.endObject()


class Master:
    def __init__(self):
        self.time_now = time.time()
        self.time_prev = self.time_now - .01666
        self.dt = .01666

        def init_tile(t):
            if 'RoadH' in t.name:
                return RoadH(t)
            elif 'RoadV' in t.name:
                return RoadV(t)
            elif 'RoadX' in t.name:
                return RoadX(t)
            else:
                return t

        self.spawns = []  #
        self.tiles = list(init_tile(o) for o in scene.objects if 'tile' in o.name and 'proxy' not in o.name)
        self.roads = list(t for t in self.tiles if 'Road' in t.name)
        self.cars = set()

        #print("Master has {} tiles".format(len(self.tiles)))

    def link_roads(self):
        for r in self.roads:
            r.link()  #
        for r in self.roads:
            r.link_ways() #

    def update(self):
        self.time_prev = self.time_now
        self.time_now = time.time()
        self.dt = self.time_now - self.time_prev
        dt = self.dt
        global z

        for s in self.spawns:
            if random() < .001666:
                # kind = choice(
                #     ('Car_Beige_proxy',
                #      'Car_Beige_proxy',
                #      'Car_Red_proxy',
                #      'Car_Green_proxy',
                #      'Car_Blue_proxy'
                #     )
                # ) 

                if z <20 and m.message == "C":
                    kind = m.name[ : -1]
                    print(kind)
                    obj = scene.addObject(kind, self.roads[0])
                    car = Car(obj, way=s)
                    car.ID = z
                    self.cars.add(car)
                    s.reach(car)
                    z=z+1

                    m.message=''

                #print(Car.get_x)          

        for r in self.roads:
            r.update(dt)

        for c in self.cars.copy():
            c.update(dt)



class mqttThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        try:
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.on_connect = self.mqtt_on_connect
            self.mqtt_client.on_message = self.mqtt_on_message
            self.message=''
            self.name=''
            self.mqtt_client.connect('localhost', 1883, 60)

            
        except socket.gaierror:
            print ('No Connection')
        #self.fallbackLoopTime = fallbackLoopTime
        
    def stopped(self):
        return self.event.isSet()

    def stop(self):
        self.event.set()

    def mqtt_on_connect(self,client, userdata,flags, rc):
        self.mqtt_client.subscribe('addcar')
        self.mqtt_client.subscribe('get_pos')
        self.mqtt_client.subscribe('datasend')


    def mqtt_on_message(self,client, userdata, msg):
        Str = str(msg.payload)
        self.message = Str[11]
        self.name = Str.split('"')[3]
        print(self.message)
        print(self.name)
        # if self.message == "b'1'":
        #     print('YES')

    def pos_publish(pos):
        self.client.publish("get_pos",pos)

    def run(self):
        self.mqtt_client.loop_start()
        #self.event.wait(self.interval)

def  screen_shot():
    cont = bge.logic.getCurrentController()
    own = cont.owner
    scene = bge.logic.getCurrentScene()
    if not 'init' in own:
        own['init'] = 1
        own['counter'] = 0

    own['counter'] += 1

    ######## APPROACH #1
    #get frame using makeScreenshot()
    frame_filename = "//frame" + str(own['counter']) + ".png"
    bge.render.makeScreenshot(frame_filename)


def  convey_photo():
    files = {'image':open('/home/zhouzhou/blender/bge-traffic/frame1.png','rb')}
    try:
        r = requests.post('http://192.168.3.24:3000/api/tk1/picture',files=files)
    except requests.exceptions.RequestException as e:
        logging.error( str(e))


M = Master()
M.link_roads()
update_master = lambda: M.update()
# screen_shot()
# time.sleep(5)
# convey_photo()

m = mqttThread()
m.run()